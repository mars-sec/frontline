"""Source adapter registry, URL canonicalization, and conditional HTTP fetch."""

from __future__ import annotations

import logging
from typing import Callable, Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from ..config import USER_AGENT, Feed
from ..models import Article
from ..store import Store

log = logging.getLogger("frontline.sources")

ACCEPT_FEED = (
    "application/rss+xml, application/atom+xml, "
    "application/xml, text/xml, */*"
)

_TRACKING_PREFIXES = (
    "utm_", "mc_", "ref", "fbclid", "gclid", "igshid", "spm",
)


def canonicalize_url(url: str) -> str:
    """Lower-case host, strip fragments and tracking params."""
    if not url:
        return ""
    try:
        parts = urlparse(url.strip())
    except ValueError:
        return url.strip()
    query = [
        (k, v) for k, v in parse_qsl(parts.query)
        if not any(k.lower().startswith(p) for p in _TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunparse((
        parts.scheme.lower() or "https",
        parts.netloc.lower(),
        path,
        "",
        urlencode(query),
        "",
    ))


def fetch_conditional(store: Store, url: str,
                      timeout: float = 20.0) -> tuple[int, str]:
    """GET url with ETag/Last-Modified from cache. Returns (status, text).

    304 means nothing changed; callers skip re-processing.
    0 means network error.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": ACCEPT_FEED}
    cached = store.get_http_cache(url)
    if cached:
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]
    try:
        resp = httpx.get(url, headers=headers, timeout=timeout,
                         follow_redirects=True)
    except httpx.HTTPError:
        return 0, ""
    if resp.status_code == 304:
        return 304, ""
    if resp.status_code == 200:
        store.set_http_cache(
            url, resp.headers.get("ETag"),
            resp.headers.get("Last-Modified"))
        return 200, resp.text
    return resp.status_code, ""


class SourceAdapter(Protocol):
    """Protocol for source adapters. Not strictly required (the registry
    uses plain functions), but useful for class-based adapters."""
    def fetch(self) -> list[Article]: ...


Collector = Callable[[Feed, Store], list[Article]]

ADAPTERS: dict[str, Collector] = {}


def register(source_type: str):
    """Decorator that registers a collect function for a source type."""
    def deco(fn: Collector) -> Collector:
        ADAPTERS[source_type] = fn
        return fn
    return deco
