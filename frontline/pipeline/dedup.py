"""Embedding-based story dedup via greedy cosine clustering."""

from __future__ import annotations

import numpy as np

from ..models import Article


def _rep_key(article: Article) -> tuple[float, int]:
    return (article.weight, len(article.content or article.summary or ""))


def cluster_articles(
    pairs: list[tuple[int, Article]],
    embeddings: dict[int, np.ndarray],
    threshold: float = 0.86,
) -> list[tuple[int, Article]]:
    """Assign cluster_id and is_representative in place. Returns pairs."""
    clusters: list[dict] = []

    for article_id, article in pairs:
        vec = embeddings.get(article_id)
        if vec is None:
            article.cluster_id = str(article_id)
            article.is_representative = True
            continue

        best_i, best_sim = -1, 0.0
        for idx, cl in enumerate(clusters):
            sim = float(np.dot(vec, cl["centroid"]))
            if sim > best_sim:
                best_i, best_sim = idx, sim

        if best_i >= 0 and best_sim >= threshold:
            cl = clusters[best_i]
            cl["members"].append((article_id, article))
            n = cl["count"]
            cl["centroid"] = (cl["centroid"] * n + vec) / (n + 1)
            cl["count"] = n + 1
        else:
            clusters.append({
                "centroid": vec.copy(),
                "count": 1,
                "members": [(article_id, article)],
            })

    for cl in clusters:
        members = cl["members"]
        rep_id, rep = max(members, key=lambda p: _rep_key(p[1]))
        other_sources = [a.source for aid, a in members if aid != rep_id]
        for aid, a in members:
            a.cluster_id = str(rep_id)
            a.is_representative = (aid == rep_id)
            if aid == rep_id:
                a.also_covered_by = other_sources

    return pairs


def representatives(
    pairs: list[tuple[int, Article]],
) -> list[tuple[int, Article]]:
    """Return only the representative article per cluster."""
    return [(aid, a) for aid, a in pairs if a.is_representative]
