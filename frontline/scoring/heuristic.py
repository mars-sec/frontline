"""Heuristic scorer: profile-keyword matching, no API needed."""

from __future__ import annotations

import logging
import re
from collections import Counter

from ..config import Settings, load_profile
from ..models import Article, Score

log = logging.getLogger("frontline.scoring.heuristic")

_FLUFF_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bpress release\b",
        r"\bwe are (pleased|excited|thrilled|proud)\b",
        r"\bwe'?re (pleased|excited|thrilled|proud)\b",
        r"\bindustry.leading\b",
        r"\bnext.gen(eration)?\b",
        r"\bsynerg",
        r"\bgame.chang",
        r"\bparadigm shift\b",
        r"\bleverage\b",
        r"\bscalable solution\b",
        r"\bunlock(ing)? (value|potential|growth)\b",
        r"\btransform(ative|ing)\b",
        r"\bholistic\b",
        r"\bseamless(ly)?\b",
        r"\bcutting.edge\b",
        r"\bone.stop.shop\b",
        r"\brobust (platform|solution)\b",
    ]
]

_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "shall", "should", "may", "might", "can", "could", "that", "this",
    "these", "those", "i", "you", "he", "she", "it", "we", "they", "my",
    "your", "his", "her", "its", "our", "their", "what", "which", "who",
    "when", "where", "why", "how", "not", "no", "so", "if", "then", "than",
    "as", "about", "into", "through", "during", "before", "after", "above",
    "below", "between", "all", "each", "every", "both", "few", "more",
    "most", "other", "some", "such", "only", "also", "just", "very",
})

_TOKEN_RE = re.compile(r"[a-z][a-z0-9+#._-]{1,40}")


def _extract_profile_keywords(profile: str) -> set[str]:
    """Pull meaningful tokens from the profile text."""
    tokens = _TOKEN_RE.findall(profile.lower())
    return {t for t in tokens if t not in _STOP_WORDS and len(t) > 2}


class HeuristicScorer:
    name = "heuristic"
    model = "keyword-v1"

    def __init__(self, settings: Settings):
        self.settings = settings
        profile = load_profile()
        self._keywords = _extract_profile_keywords(profile)
        self._sections = settings.sections
        log.debug("heuristic scorer loaded %d profile keywords",
                  len(self._keywords))

    def score(self, article_id: int, article: Article) -> Score:
        text = (article.text_for_scoring() or "").lower()
        title = article.title.lower()

        fluff_count = sum(1 for p in _FLUFF_PATTERNS if p.search(text))
        is_fluff = fluff_count >= 2

        tokens = _TOKEN_RE.findall(text + " " + title)
        token_counts = Counter(tokens)

        hits = sum(token_counts[kw] for kw in self._keywords if kw in token_counts)

        if hits >= 8:
            base = 8.0
        elif hits >= 5:
            base = 6.5
        elif hits >= 3:
            base = 5.0
        elif hits >= 1:
            base = 3.0
        else:
            base = 1.0

        base *= article.weight

        if article.actively_exploited:
            base += 1.5
        if article.has_poc:
            base += 0.5
        if is_fluff:
            base *= 0.4

        score_val = max(0.0, min(10.0, base))

        section = self._guess_section(token_counts)

        top_hits = sorted(
            [(kw, token_counts[kw]) for kw in self._keywords if kw in token_counts],
            key=lambda x: x[1], reverse=True,
        )[:5]
        reason = f"matched {hits} profile keywords" if hits else "no keyword matches"
        if top_hits:
            reason += f" (top: {', '.join(kw for kw, _ in top_hits[:3])})"

        return Score(
            article_id=article_id,
            score=round(score_val, 1),
            section=section,
            reason=reason[:300],
            tldr="",
            is_fluff=is_fluff,
            backend="heuristic",
            model=self.model,
        )

    def _guess_section(self, token_counts: Counter) -> str:
        """Naive section assignment: pick the section name with the most
        matching tokens in the article."""
        best, best_count = "Other", 0
        for section in self._sections:
            section_tokens = _TOKEN_RE.findall(section.lower())
            count = sum(token_counts.get(t, 0) for t in section_tokens)
            if count > best_count:
                best, best_count = section, count
        return best
