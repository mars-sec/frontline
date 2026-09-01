"""Edition composer: Claude, Ollama, or heuristic backends."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict

from .config import Settings, load_profile
from .models import Edition, EditionSection, EditionStory
from .store import Store

log = logging.getLogger("frontline.editor")

STORY_SCHEMA = {
    "type": "object",
    "properties": {
        "article_id": {"type": "integer"},
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "why_you_care": {"type": "string"},
    },
    "required": ["article_id", "headline", "summary", "why_you_care"],
    "additionalProperties": False,
}

EDITION_SCHEMA = {
    "type": "object",
    "properties": {
        "editors_letter": {"type": "string"},
        "lead": STORY_SCHEMA,
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "stories": {"type": "array", "items": STORY_SCHEMA},
                },
                "required": ["name", "stories"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["editors_letter", "lead", "sections"],
    "additionalProperties": False,
}

SYSTEM = (
    "You are the editor-in-chief of a daily news digest with exactly one "
    "reader, described in the profile below. You summarize already-published "
    "articles so the reader stays informed — this is journalism about the "
    "news, not a how-to guide. Report on developments at a descriptive, "
    "newsworthy level: what was disclosed or published, who is affected, and "
    "why it matters. Do not reproduce step-by-step offensive procedures, "
    "exploit code, or operational instructions — summarize that such research "
    "exists and what it means, the way a trade publication would.\n\n"
    "From the candidate articles, compose today's edition:\n"
    "- Pick the single most important story as the lead.\n"
    "- Group the rest into 2-5 sections (drop weak or duplicate stories; "
    "a tight paper beats a padded one).\n"
    "- For each story write: a sharp headline in the paper's own voice (not "
    "the source's), a 2-4 sentence summary of what was published and why it "
    "matters, and one 'why this is on your radar' sentence connecting it to "
    "the reader's interests.\n"
    "- Write a 3-5 sentence editor's letter connecting today's themes to the "
    "reader's world. Warm, wry, no fluff.\n"
    "Never invent facts not in the article text. Refer to articles only by "
    "their numeric id.\n\n"
    "Return your answer as a single JSON object with keys: editors_letter, "
    "lead, sections. Each story object has keys: article_id, headline, "
    "summary, why_you_care. Each section has keys: name, stories.\n\n"
    "READER PROFILE:\n"
)


def _candidates_payload(rows, clip: int) -> str:
    items = [{
        "id": row["id"],
        "title": row["title"],
        "source": row["source"],
        "published": row["published"],
        "triage_section": row["section"],
        "triage_score": row["score"],
        "text": (row["content"] or row["summary"] or "")[:clip],
    } for row in rows]
    return json.dumps(items, ensure_ascii=False)


def _refusal(message) -> bool:
    return getattr(message, "stop_reason", None) == "refusal"


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


# Public API


def compose_edition(store: Store, settings: Settings,
                    use_batch: bool = False) -> Edition | None:
    """Compose an edition using the configured backend.

    Routes to Claude, Ollama, or heuristic based on scoring_backend.
    Returns an Edition on success, None if no articles qualify.
    """
    backend = settings.scoring_backend

    if backend == "claude":
        return _claude_edition(store, settings, use_batch)
    elif backend == "ollama":
        return _ollama_edition(store, settings)
    else:
        return _heuristic_edition(store, settings)


# Claude path


def _claude_edition(store: Store, settings: Settings,
                    use_batch: bool) -> Edition | None:
    from .llm import LLM, text_of

    rows = _get_candidates(store, settings)
    if not rows:
        return None

    llm = LLM(store, settings.batch_poll_seconds)
    profile = load_profile()

    base = dict(
        max_tokens=16000,
        system=[{"type": "text", "text": SYSTEM + profile,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content":
                   "Candidate articles (JSON):\n"
                   + _candidates_payload(rows, settings.editor_clip_chars)}],
        output_config={
            "format": {"type": "json_schema", "schema": EDITION_SCHEMA}},
    )

    primary = settings.models.get("editor", "claude-sonnet-5")
    if use_batch:
        results = llm.run_batch(
            "editor", [{"custom_id": "edition",
                        "params": {**base, "model": primary}}])
        message = results.get("edition")
    else:
        message = llm.create("editor", **base, model=primary)

    if message is None:
        log.error("editor request failed")
        return None

    fb = settings.editor_fallback
    if _refusal(message) and fb and fb != primary:
        log.warning("primary editor (%s) hit safety refusal, falling "
                    "back to %s", primary, fb)
        message = llm.create("editor", **base, model=fb)

    if message is None or _refusal(message):
        log.error("editor declined to write this edition (safety refusal)")
        return None

    try:
        data = json.loads(text_of(message))
    except json.JSONDecodeError as exc:
        log.error("editor returned invalid JSON: %s", exc)
        return None

    return _resolve_edition(data, rows, store)


# Ollama path


def _ollama_edition(store: Store, settings: Settings) -> Edition | None:
    try:
        import ollama as _ollama
    except ImportError:
        raise RuntimeError(
            "ollama package not installed. "
            "Install with: pip install 'frontline[ollama]'"
        )

    rows = _get_candidates(store, settings)
    if not rows:
        return None

    profile = load_profile()
    user_msg = ("Candidate articles (JSON):\n"
                + _candidates_payload(rows, settings.editor_clip_chars))

    model = settings.ollama_model
    log.info("composing edition with ollama (%s)...", model)

    try:
        resp = _ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM + profile},
                {"role": "user", "content": user_msg},
            ],
            format="json",
        )
        text = resp.get("message", {}).get("content", "")
    except Exception:
        log.error("ollama editor call failed", exc_info=True)
        return None

    match = _JSON_RE.search(text)
    if not match:
        log.error("ollama editor returned no JSON")
        return None

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        log.error("ollama editor returned invalid JSON: %s", exc)
        return None

    return _resolve_edition(data, rows, store)


# Heuristic path


def _heuristic_edition(store: Store, settings: Settings) -> Edition | None:
    """Arrange scored articles into sections without any LLM."""
    rows = _get_candidates(store, settings)
    if not rows:
        return None

    log.info("composing heuristic edition from %d articles", len(rows))

    lead_row = rows[0]
    lead = EditionStory(
        article_id=lead_row["id"],
        headline=lead_row["title"],
        summary=lead_row["tldr"] or lead_row["summary"] or "",
        why_you_care=lead_row["reason"] or "",
        url=lead_row["url"],
        source=lead_row["source"],
        published=lead_row["published"] or "",
    )

    by_section: dict[str, list] = defaultdict(list)
    for row in rows[1:]:
        section_name = row["section"] or "Other"
        by_section[section_name].append(EditionStory(
            article_id=row["id"],
            headline=row["title"],
            summary=row["tldr"] or row["summary"] or "",
            why_you_care=row["reason"] or "",
            url=row["url"],
            source=row["source"],
            published=row["published"] or "",
        ))

    sections = [
        EditionSection(name=name, stories=stories)
        for name, stories in by_section.items()
        if stories
    ]

    used = [lead.article_id]
    for sec in sections:
        for s in sec.stories:
            if s.article_id not in used:
                used.append(s.article_id)

    return Edition(
        date="",
        editors_letter="Today's top stories, curated from your feeds.",
        lead=lead,
        sections=sections,
        article_ids=used,
    )


# Shared helpers


def _get_candidates(store: Store, settings: Settings):
    rows = store.candidates(
        settings.min_score, settings.top_articles,
        settings.window_days, settings.drop_fluff)

    if len(rows) < settings.min_articles:
        relaxed = store.candidates(
            0, settings.top_articles,
            settings.window_days, settings.drop_fluff)
        if len(relaxed) > len(rows):
            log.info("only %d articles above min_score %.1f; relaxed "
                     "threshold to fill min_articles=%d (got %d)",
                     len(rows), settings.min_score,
                     settings.min_articles, len(relaxed))
            rows = relaxed

    if not rows:
        log.warning("no articles scored high enough for an edition")
        return None
    log.info("editor has %d candidate articles", len(rows))
    return rows


def _resolve_edition(data: dict, rows, store: Store) -> Edition:
    """Convert raw editor JSON into an Edition model, validating IDs."""
    valid_ids = {row["id"] for row in rows}

    def resolve_story(story: dict) -> EditionStory | None:
        aid = story.get("article_id")
        if aid not in valid_ids:
            return None
        row = store.get_article(aid)
        if row is None:
            return None
        return EditionStory(
            article_id=aid,
            headline=story.get("headline", ""),
            summary=story.get("summary", ""),
            why_you_care=story.get("why_you_care", ""),
            url=row["url"],
            source=row["source"],
            published=row["published"] or "",
        )

    lead_data = data.get("lead", {})
    lead = resolve_story(lead_data)
    if lead is None:
        row = rows[0]
        lead = EditionStory(
            article_id=row["id"],
            headline=row["title"],
            summary=row["summary"] or "",
            why_you_care="",
            url=row["url"],
            source=row["source"],
            published=row["published"] or "",
        )

    sections = []
    for sec_data in data.get("sections", []):
        stories = []
        for s in sec_data.get("stories", []):
            resolved = resolve_story(s)
            if resolved and resolved.article_id != lead.article_id:
                stories.append(resolved)
        if stories:
            sections.append(EditionSection(
                name=sec_data.get("name", "Other"),
                stories=stories,
            ))

    used = [lead.article_id]
    for sec in sections:
        for s in sec.stories:
            if s.article_id not in used:
                used.append(s.article_id)

    return Edition(
        date="",
        editors_letter=data.get("editors_letter", ""),
        lead=lead,
        sections=sections,
        article_ids=used,
    )
