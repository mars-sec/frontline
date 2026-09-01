"""CVE extraction, KEV cross-reference, and PoC detection."""

from __future__ import annotations

import re

from ..models import Article

CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)

_POC_HINTS = re.compile(
    r"\b(proof[- ]of[- ]concept|\bpoc\b|exploit code|working exploit|"
    r"metasploit module|nuclei template|github\.com/\S+/\S+)\b",
    re.IGNORECASE,
)


def enrich(article: Article, kev_cves: set[str]) -> Article:
    """Fill CVE ids and exploitation/PoC flags in place."""
    haystack = f"{article.title}\n{article.summary}\n{article.content}"
    found = {m.upper() for m in CVE_RE.findall(haystack)}
    found.update(c.upper() for c in article.cve_ids)
    article.cve_ids = sorted(found)

    if article.cve_ids and any(c in kev_cves for c in article.cve_ids):
        article.actively_exploited = True
    if _POC_HINTS.search(haystack):
        article.has_poc = True
    return article


def build_kev_set(articles: list[Article]) -> set[str]:
    """Collect CVE ids from KEV-sourced articles for cross-reference."""
    kev: set[str] = set()
    for a in articles:
        if a.source_type == "cve_kev":
            kev.update(c.upper() for c in a.cve_ids)
    return kev
