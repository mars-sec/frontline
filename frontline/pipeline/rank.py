"""Final ranking: score * weight * recency decay."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import sqlite3


def _recency(published: str | None, half_life_hours: float,
             now: datetime) -> float:
    if not published:
        return 0.5
    try:
        pub = datetime.fromisoformat(published)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (now - pub).total_seconds() / 3600.0)
        return math.pow(0.5, age_h / max(1e-6, half_life_hours))
    except (ValueError, TypeError):
        return 0.5


def compute_ranks(
    rows: list[sqlite3.Row],
    relevance_weight: float = 0.75,
    recency_weight: float = 0.25,
    half_life_hours: float = 36.0,
    now: datetime | None = None,
) -> list[tuple[sqlite3.Row, float]]:
    """Compute a composite rank for each scored article row.

    Returns (row, rank) pairs sorted best-first.
    """
    now = now or datetime.now(timezone.utc)
    ranked = []
    for row in rows:
        weight = row["weight"] if "weight" in row.keys() else 1.0
        weight_factor = 0.6 + 0.4 * min(2.0, weight) / 2.0
        rel = (row["score"] / 10.0) * weight_factor
        rec = _recency(row["published"], half_life_hours, now)
        rank = relevance_weight * rel + recency_weight * rec
        ranked.append((row, rank))
    ranked.sort(key=lambda p: p[1], reverse=True)
    return ranked


def select_top(
    ranked: list[tuple[sqlite3.Row, float]],
    min_score: float = 4.0,
    top_n: int = 30,
    drop_fluff: bool = True,
    max_per_section: int = 8,
) -> list[tuple[sqlite3.Row, float]]:
    """Filter and cap the ranked list for the front page."""
    out: list[tuple[sqlite3.Row, float]] = []
    per_section: dict[str, int] = {}

    for row, rank in ranked:
        if drop_fluff and row["is_fluff"] and not row["actively_exploited"]:
            continue
        if row["score"] < min_score and not row["actively_exploited"]:
            continue
        section = row["section"]
        if per_section.get(section, 0) >= max_per_section:
            continue
        out.append((row, rank))
        per_section[section] = per_section.get(section, 0) + 1
        if len(out) >= top_n:
            break
    return out
