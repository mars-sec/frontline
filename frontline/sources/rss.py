"""RSS/Atom collector with conditional GET."""

from __future__ import annotations

import logging
from calendar import timegm
from datetime import datetime, timezone

import feedparser

from ..config import Feed
from ..models import Article
from ..store import Store
from ..textutil import html_to_text
from .base import canonicalize_url, fetch_conditional, register

log = logging.getLogger("frontline.sources.rss")


def _entry_datetime(entry) -> str:
    """Extract publication time as ISO 8601. Uses timegm (not mktime, which breaks on Windows)."""
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try:
                dt = datetime.fromtimestamp(timegm(val), tz=timezone.utc)
                return dt.isoformat()
            except (ValueError, OverflowError, OSError):
                continue
    return ""


def _entry_summary(entry) -> str:
    candidates = [entry.get("summary", "")]
    for content in entry.get("content", []) or []:
        candidates.append(content.get("value", ""))
    return max(candidates, key=len) if candidates else ""


@register("rss")
def collect_rss(feed: Feed, store: Store,
                max_entries: int = 25) -> list[Article]:
    status, text = fetch_conditional(store, feed.url)
    if status == 304:
        log.debug("%s: not modified (304)", feed.name)
        return []
    if not text:
        log.warning("%s: empty response (status %d)", feed.name, status)
        return []

    parsed = feedparser.parse(text)
    if parsed.bozo and not parsed.entries:
        log.warning("%s: unreadable feed (%s)", feed.name,
                    parsed.bozo_exception)
        return []

    articles: list[Article] = []
    for entry in parsed.entries[:max_entries]:
        link = entry.get("link", "")
        url = canonicalize_url(link)
        title = html_to_text(entry.get("title", "")).strip()
        if not url or not title:
            continue
        summary = html_to_text(_entry_summary(entry))[:2000]
        articles.append(Article(
            url=url,
            title=title,
            source=feed.name,
            published=_entry_datetime(entry),
            summary=summary,
            weight=feed.weight,
            source_type="rss",
        ))
    return articles
