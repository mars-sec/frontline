"""CISA Known Exploited Vulnerabilities (KEV) collector."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from ..config import Feed
from ..models import Article
from ..store import Store
from .base import fetch_conditional, register

log = logging.getLogger("frontline.sources.cve_kev")

_NVD = "https://nvd.nist.gov/vuln/detail/"


def _parse_date(value: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return ""


@register("cve_kev")
def collect_kev(feed: Feed, store: Store) -> list[Article]:
    status, text = fetch_conditional(store, feed.url)
    if status == 304 or not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("KEV: invalid JSON response")
        return []

    articles: list[Article] = []
    for vuln in data.get("vulnerabilities", []):
        cve = vuln.get("cveID", "")
        if not cve:
            continue
        vendor = vuln.get("vendorProject", "")
        product = vuln.get("product", "")
        name = vuln.get("vulnerabilityName", cve)
        title = f"[KEV] {cve}: {name} ({vendor} {product})".strip()
        summary_parts = [
            vuln.get("shortDescription", ""),
            (f"Required action: {vuln.get('requiredAction', '')}."
             if vuln.get("requiredAction") else ""),
            (f"Known ransomware use: "
             f"{vuln.get('knownRansomwareCampaignUse', 'Unknown')}."),
        ]
        url = f"{_NVD}{cve}"
        articles.append(Article(
            url=url,
            title=title,
            source=feed.name,
            source_type="cve_kev",
            published=_parse_date(vuln.get("dateAdded", "")),
            summary=" ".join(p for p in summary_parts if p),
            content=vuln.get("shortDescription", ""),
            weight=feed.weight,
            cve_ids=[cve],
            actively_exploited=True,
        ))
    return articles
