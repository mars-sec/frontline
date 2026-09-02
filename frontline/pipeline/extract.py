"""Full-text extraction via trafilatura. Best-effort, never fatal."""

from __future__ import annotations

import logging

import httpx

from ..config import USER_AGENT
from ..models import Article

log = logging.getLogger("frontline.extract")

_SKIP_TYPES = {"cve_kev"}

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=20.0,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )
    return _client


def extract_fulltext(article: Article, timeout: float = 20.0,
                     min_chars: int = 400) -> Article:
    """Populate article.content in place. Returns the same article."""
    if article.source_type in _SKIP_TYPES:
        article.content = article.content or article.summary
        return article
    if not article.url:
        article.content = article.summary
        return article
    try:
        import trafilatura

        resp = _get_client().get(article.url, timeout=timeout)
        if resp.status_code == 200 and resp.text:
            body = trafilatura.extract(
                resp.text, include_comments=False,
                include_tables=False, favor_recall=True,
            )
            if body and len(body) >= min_chars:
                article.content = body
                return article
    except Exception as exc:
        log.debug("extract failed for %s: %s", article.url, exc)
    article.content = article.content or article.summary or article.title
    return article
