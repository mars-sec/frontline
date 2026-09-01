"""Claude scorer: structured output with prompt caching."""

from __future__ import annotations

import logging

from ..config import Settings, load_profile
from ..llm import LLM
from ..models import Article, Score
from ..store import Store
from .base import build_system_prompt, build_user_prompt, parse_judgment
from .fewshot import build_fewshot

log = logging.getLogger("frontline.scoring.claude")

TRIAGE_SCHEMA = {
    "name": "triage",
    "description": "Score one article for relevance and assign a section.",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {
                "type": "number",
                "description": "0-10 relevance score.",
            },
            "section": {
                "type": "string",
                "description": "Best-fit section name.",
            },
            "reason": {
                "type": "string",
                "description": "One sentence, max 25 words.",
            },
            "tldr": {
                "type": "string",
                "description": "One or two sentence summary.",
            },
            "is_fluff": {
                "type": "boolean",
                "description": "True if vendor marketing or no substance.",
            },
        },
        "required": ["score", "section", "reason", "tldr", "is_fluff"],
    },
}


class ClaudeScorer:
    name = "claude"

    def __init__(self, settings: Settings, store: Store, llm: LLM | None = None):
        self.settings = settings
        self.store = store
        self.model = settings.models.get("triage", "claude-haiku-4-5-20251001")
        self._llm = llm or LLM(store, settings.batch_poll_seconds)
        self._profile = load_profile()
        self._fewshot = build_fewshot(store)
        self._system_prompt = build_system_prompt(
            self._profile, settings.sections, self._fewshot,
        )

    @property
    def llm(self) -> LLM:
        return self._llm

    def _cached_system(self) -> list[dict]:
        return [{
            "type": "text",
            "text": self._system_prompt,
            "cache_control": {"type": "ephemeral"},
        }]

    def score(self, article_id: int, article: Article) -> Score:
        user_msg = build_user_prompt(article)
        try:
            return self._score_structured(article_id, user_msg)
        except Exception:
            log.debug("structured output unavailable, falling back to text",
                      exc_info=True)
            return self._score_text(article_id, user_msg)

    def _score_structured(self, article_id: int, user_msg: str) -> Score:
        resp = self._llm.create(
            stage="triage",
            model=self.model,
            max_tokens=400,
            system=self._cached_system(),
            messages=[{"role": "user", "content": user_msg}],
            tools=[TRIAGE_SCHEMA],
            tool_choice={"type": "tool", "name": "triage"},
        )
        for block in resp.content:
            if block.type == "tool_use" and block.name == "triage":
                data = block.input
                score_val = max(0.0, min(10.0, float(data.get("score", 0))))
                return Score(
                    article_id=article_id,
                    score=score_val,
                    section=str(data.get("section", "Other")).strip(),
                    reason=str(data.get("reason", ""))[:300],
                    tldr=str(data.get("tldr", ""))[:600],
                    is_fluff=bool(data.get("is_fluff", False)),
                    backend="claude",
                    model=self.model,
                )
        return parse_judgment("", article_id, "claude", self.model)

    def _score_text(self, article_id: int, user_msg: str) -> Score:
        resp = self._llm.create(
            stage="triage",
            model=self.model,
            max_tokens=400,
            system=self._cached_system(),
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text if resp.content else ""
        return parse_judgment(text, article_id, "claude", self.model)
