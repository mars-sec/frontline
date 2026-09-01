"""Feed discovery via Claude web search. Claude-only."""

from __future__ import annotations

import json
import logging
import re

import feedparser

from .config import USER_AGENT, Feed, Settings, load_feeds, load_profile, save_feeds
from .llm import LLM
from .store import Store

log = logging.getLogger("frontline.discover")

PROMPT = """\
Below is my reader profile. Find RSS or Atom feeds I should follow
for a personalized daily newspaper. Search the web for the best sources —
niche blogs and primary sources beat big aggregators. Match my specific
interests and anti-interests closely; skip generic outlets that only
occasionally touch my topics. Remember that Substack publications (/feed),
subreddits (reddit.com/r/NAME/.rss), arXiv categories (rss.arxiv.org/rss/CAT),
vendor research blogs, and most personal blogs expose feeds.

Propose 20-35 feeds, weighted toward primary and technical sources. End your
reply with ONLY a fenced ```json code block: a list of objects
{"name": ..., "url": <the feed URL itself, not the site>,
"why": <one short sentence>}.
{topics}
READER PROFILE:
"""

_JSON_BLOCK = re.compile(r"```json\s*(.*?)```", re.DOTALL)


def _topics_hint(sections: list[str]) -> str:
    generic = {"Technology", "Science & Research", "Business & Economy",
               "World", "Culture & Ideas", "Your Projects", "Other"}
    custom = [s for s in sections if s not in generic]
    if not custom:
        return ""
    return ("\nI especially want strong coverage of these topics: "
            + ", ".join(custom) + ".\n")


def _proposed_feeds(reply: str) -> list[dict]:
    match = None
    for match in _JSON_BLOCK.finditer(reply):
        pass
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
        return [d for d in data if isinstance(d, dict) and d.get("url")]
    except json.JSONDecodeError:
        return []


def _verify(url: str) -> bool:
    try:
        parsed = feedparser.parse(url, agent=USER_AGENT)
        return bool(parsed.entries)
    except Exception:
        return False


def discover(settings: Settings, store: Store,
             max_searches: int = 15) -> list[tuple[Feed, str]]:
    """Find feeds via web search and add to sources.yaml. Returns [(Feed, why)]."""
    profile = load_profile()
    llm = LLM(store, settings.batch_poll_seconds)
    model = settings.models.get("discover", "claude-sonnet-5")

    log.info("asking %s (web search, max %d searches) for feed ideas...",
             model, max_searches)
    print(f"Asking {model} (web search, max {max_searches} searches) "
          f"for feed ideas...")

    prompt = PROMPT.replace("{topics}", _topics_hint(settings.sections))
    messages: list[dict] = [{"role": "user", "content": prompt + profile}]
    tools = [{"type": "web_search_20260209", "name": "web_search",
              "max_uses": max_searches}]

    while True:
        response = llm.create("discover", model=model, max_tokens=16000,
                              tools=tools, messages=messages)
        if response is None:
            log.error("discover request failed")
            print("Discovery request failed.")
            return []
        if getattr(response, "stop_reason", None) == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        break

    full_text = "\n".join(b.text for b in response.content if b.type == "text")
    proposals = _proposed_feeds(full_text)
    if not proposals:
        print("No feed list found in the reply. Try again or add feeds "
              "by hand.")
        return []

    existing = load_feeds()
    known = {f.url for f in existing}
    added: list[tuple[Feed, str]] = []
    dead: list[str] = []
    dupes = 0

    for p in proposals:
        url = p["url"].strip()
        if url in known:
            dupes += 1
            continue
        print(f"  verifying {url} ...", end=" ", flush=True)
        if _verify(url):
            print("ok")
            feed = Feed(name=p.get("name", url), url=url)
            existing.append(feed)
            known.add(url)
            added.append((feed, p.get("why", "")))
        else:
            print("dead/not-a-feed, skipped")
            dead.append(url)

    if added:
        save_feeds(existing)

    print(f"\nAdded {len(added)} feeds to config/sources.yaml "
          f"({dupes} already present, {len(dead)} failed verification):")
    for feed, why in added:
        print(f"  + {feed.name} - {why}")

    return added
