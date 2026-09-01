"""Stage-0 embedding pre-filter. Drops ~70-80% before LLM scoring."""

from __future__ import annotations

import logging

import numpy as np

from ..config import Settings
from ..embeddings import Embedder
from ..store import Store

log = logging.getLogger("frontline.prefilter")


def _centroid(vectors: list[np.ndarray]) -> np.ndarray | None:
    if not vectors:
        return None
    mat = np.vstack(vectors)
    c = mat.mean(axis=0)
    norm = np.linalg.norm(c)
    return (c / norm).astype(np.float32) if norm else None


def prefilter(
    article_ids: list[int],
    embeddings: dict[int, np.ndarray],
    embedder: Embedder,
    store: Store,
    profile_text: str,
    settings: Settings,
) -> list[int]:
    """Return the subset of article IDs worth sending to the LLM scorer."""
    pf = settings.prefilter
    if not pf.enabled:
        return article_ids[:pf.max_llm_items]

    if len(article_ids) <= pf.min_candidates:
        return article_ids[:pf.max_llm_items]

    profile_vec = embedder.embed([profile_text])[0]

    liked_fb = store.get_feedback(limit=100)
    liked_ids = [r["article_id"] for r in liked_fb if r["vote"] > 0]
    liked_embs = store.get_embeddings(liked_ids)
    liked_centroid = _centroid(list(liked_embs.values()))

    scored: list[tuple[float, int]] = []
    forced: list[int] = []

    for aid in article_ids:
        row = store.get_article(aid)
        if row and row["actively_exploited"]:
            forced.append(aid)
            continue
        vec = embeddings.get(aid)
        if vec is None:
            scored.append((0.0, aid))
            continue
        sim = float(np.dot(vec, profile_vec))
        if liked_centroid is not None:
            sim = max(sim, float(np.dot(vec, liked_centroid)))
        scored.append((sim, aid))

    scored.sort(key=lambda t: t[0], reverse=True)
    keep_n = max(pf.min_candidates, int(len(article_ids) * pf.keep_fraction))
    kept = [aid for _, aid in scored[:keep_n]]

    seen = set(kept)
    for aid in forced:
        if aid not in seen:
            kept.append(aid)
            seen.add(aid)

    log.info("stage0 kept %d of %d (+%d forced KEV)",
             len(kept), len(article_ids), len(forced))
    return kept[:pf.max_llm_items]
