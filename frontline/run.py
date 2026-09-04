"""Pipeline runner: collect, extract, enrich, embed, dedup, score, rank."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from .config import Settings, load_feeds, load_profile, load_settings
from .embeddings import get_embedder
from .models import Article
from .pipeline.dedup import cluster_articles, representatives
from .pipeline.enrich import build_kev_set, enrich
from .pipeline.extract import close_client as close_extract_client, extract_fulltext
from .pipeline.prefilter import prefilter
from .pipeline.rank import compute_ranks, select_top
from .scoring import get_scorer
from .sources import ADAPTERS
from .sources.base import close_client as close_source_client
from .store import Store

log = logging.getLogger("frontline.run")


def _collect(settings: Settings, store: Store) -> list[tuple[int, Article]]:
    """Collect from all enabled feeds and insert into the store.

    Returns (db_id, article) pairs for newly inserted articles.
    """
    feeds = [f for f in load_feeds() if f.enabled]
    if not feeds:
        log.warning("no enabled feeds. Add feeds via 'frontline discover' "
                    "or edit config/sources.yaml")
        return []

    new: list[tuple[int, Article]] = []
    for feed in feeds:
        adapter = ADAPTERS.get(feed.type)
        if adapter is None:
            log.warning("no adapter for type %r (%s)", feed.type, feed.name)
            continue
        try:
            articles = adapter(feed, store,
                               max_entries=settings.max_articles_per_feed)
            feed_new = 0
            for article in articles:
                db_id = store.add_article(article)
                if db_id is not None:
                    new.append((db_id, article))
                    feed_new += 1
            log.info("collected %d from %s (%d new)",
                     len(articles), feed.name, feed_new)
        except Exception as exc:
            log.warning("collector failed for %s: %s", feed.name, exc)

    log.info("collection complete: %d new articles", len(new))
    return new


def _extract(new_articles: list[tuple[int, Article]],
             store: Store) -> None:
    """Extract full text in parallel for articles missing a body."""
    to_extract = [
        (db_id, article) for db_id, article in new_articles
        if not article.content and article.source_type != "cve_kev"
    ]
    if not to_extract:
        return

    log.info("extracting full text for %d articles...", len(to_extract))

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(extract_fulltext, article): (db_id, article)
            for db_id, article in to_extract
        }
        done = 0
        for f in as_completed(futures):
            db_id, article = futures[f]
            try:
                f.result()
                if article.content:
                    store.set_content(db_id, article.content)
                    done += 1
            except Exception as exc:
                log.debug("extraction error for %s: %s", article.url, exc)
    log.info("extracted %d/%d articles", done, len(to_extract))


def _enrich(new_articles: list[tuple[int, Article]],
            store: Store) -> None:
    """Enrich articles with CVE/KEV/PoC signals."""
    articles = [a for _, a in new_articles]
    kev = build_kev_set(articles)
    for db_id, article in new_articles:
        enrich(article, kev)
        if article.cve_ids or article.actively_exploited or article.has_poc:
            store.update_enrichment(
                db_id, article.cve_ids,
                article.actively_exploited, article.has_poc)


def run_cycle(settings: Settings | None = None,
              rescore: bool = False) -> dict:
    """Run one full pipeline cycle. Returns a summary dict."""
    settings = settings or load_settings()
    store = Store()
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=settings.window_days)

    # 1) Collect
    new_articles = _collect(settings, store)

    # 2) Extract full text (parallel, best-effort)
    _extract(new_articles, store)

    # 3) Enrich (CVE ids, KEV cross-ref, PoC hints)
    _enrich(new_articles, store)

    # Close HTTP clients to free TCP connections before scoring
    close_source_client()
    close_extract_client()

    # 4) Load the full scoring window from DB
    window_rows = store.get_articles_since(since)
    window_ids = [r["id"] for r in window_rows]
    log.info("scoring window: %d articles", len(window_ids))

    if not window_ids:
        return {"collected": len(new_articles), "new": len(new_articles),
                "window": 0, "scored": 0, "top": 0}

    # 5) Rescore if requested
    if rescore and window_ids:
        store.delete_scores(window_ids)
        log.info("rescore: cleared scores for %d articles", len(window_ids))

    # 6) Embed articles missing embeddings
    embedder = get_embedder(settings)
    missing_emb = [
        r for r in window_rows
        if store.get_embedding(r["id"]) is None
    ]
    if missing_emb:
        texts = [
            f"{r['title']}\n{(r['content'] or r['summary'] or '')[:2000]}"
            for r in missing_emb
        ]
        vecs = embedder.embed(texts)
        for r, vec in zip(missing_emb, vecs):
            store.save_embedding(r["id"], vec)
        log.info("embedded %d articles", len(missing_emb))

    all_emb = store.get_embeddings(window_ids)

    # 7) Cluster (story dedup)
    window_pairs: list[tuple[int, Article]] = []
    for r in window_rows:
        a = Article(
            url=r["url"], title=r["title"], source=r["source"],
            published=r["published"] or "", summary=r["summary"] or "",
            content=r["content"] or "", weight=r["weight"],
            source_type=r["source_type"] or "rss",
            actively_exploited=bool(r["actively_exploited"]),
            has_poc=bool(r["has_poc"]),
        )
        if r["cve_ids"]:
            a.cve_ids = r["cve_ids"].split(",")
        window_pairs.append((r["id"], a))

    cluster_articles(window_pairs, all_emb, settings.dedup.similarity_threshold)
    for aid, a in window_pairs:
        store.update_cluster(aid, a.cluster_id, a.is_representative)

    rep_pairs = representatives(window_pairs)
    rep_ids = [aid for aid, _ in rep_pairs]
    log.info("dedup: %d clusters from %d articles, %d representatives",
             len(set(a.cluster_id for _, a in window_pairs if a.cluster_id)),
             len(window_pairs), len(rep_pairs))

    # 8) Find unscored representatives
    unscored_ids = [
        aid for aid in rep_ids
        if store.get_score(aid) is None
    ]

    # 9) Pre-filter (Stage 0)
    profile = load_profile()
    if unscored_ids:
        candidates = prefilter(
            unscored_ids, all_emb, embedder, store, profile, settings)
    else:
        candidates = []

    # 10) Score
    scorer = get_scorer(settings, store)
    scored_count = 0
    if candidates:
        id_to_article = {aid: a for aid, a in window_pairs}
        for aid in candidates:
            article = id_to_article.get(aid)
            if article is None:
                continue
            score = scorer.score(aid, article)
            store.save_score(
                aid, score.score, score.section, score.reason,
                score.tldr, score.is_fluff, score.backend, score.model)
            scored_count += 1
            if settings.logging.trace_scoring:
                log.debug("score=%.1f %-16s fluff=%d | %-60.60s [%s] :: %s",
                          score.score, score.section, int(score.is_fluff),
                          article.title, article.source,
                          (score.reason or "")[:80])
        log.info("scored %d articles via %s", scored_count, scorer.name)

    # 11) Rank the whole window
    all_scored = store.candidates(
        min_score=0, limit=9999,
        window_days=settings.window_days, drop_fluff=False)
    ranked = compute_ranks(all_scored)
    top = select_top(
        ranked,
        min_score=settings.min_score,
        top_n=settings.top_articles,
        drop_fluff=settings.drop_fluff,
    )

    for row, rank in top:
        store.save_rank(row["id"], rank)

    log.info("pipeline complete: %d top articles selected", len(top))

    return {
        "collected": len(new_articles),
        "new": len(new_articles),
        "window": len(window_ids),
        "scored": scored_count,
        "top": len(top),
    }
