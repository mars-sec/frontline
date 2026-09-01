import numpy as np

from tests.conftest import make_article

from frontline.embeddings import HashingEmbedder, cosine_matrix
from frontline.pipeline.dedup import cluster_articles, representatives
from frontline.pipeline.enrich import enrich, build_kev_set, CVE_RE
from frontline.pipeline.rank import compute_ranks, select_top
from frontline.sources import canonicalize_url


def test_canonicalize_strips_tracking_and_fragment():
    url = "https://Example.com/Post/?utm_source=rss&id=5#section"
    assert canonicalize_url(url) == "https://example.com/Post?id=5"


def test_hashing_embedder_shape_and_norm():
    emb = HashingEmbedder(dim=64)
    vecs = emb.embed(["hello world", "test text"])
    assert vecs.shape == (2, 64)
    assert abs(np.linalg.norm(vecs[0]) - 1.0) < 0.01


def test_cosine_matrix():
    emb = HashingEmbedder(dim=64)
    vecs = emb.embed(["hello", "hello", "totally different"])
    sim = cosine_matrix(vecs[0], vecs)
    assert sim[0] > 0.99
    assert sim[1] > 0.99
    assert sim[2] < sim[0]


def test_enrich_extracts_cves():
    art = make_article(
        title="CVE-2024-1234 exploit released",
        summary="Also mentions CVE-2024-5678",
        content="Full text here",
    )
    kev = {"CVE-2024-1234"}
    enrich(art, kev)
    assert "CVE-2024-1234" in art.cve_ids
    assert "CVE-2024-5678" in art.cve_ids
    assert art.actively_exploited is True


def test_enrich_detects_poc():
    art = make_article(
        content="working proof-of-concept exploit on github.com/x/poc",
    )
    enrich(art, set())
    assert art.has_poc is True


def test_build_kev_set():
    kev_art = make_article(source_type="cve_kev")
    kev_art.cve_ids = ["CVE-2025-9999"]
    kev_art.actively_exploited = True
    kev_set = build_kev_set([kev_art])
    assert "CVE-2025-9999" in kev_set


def test_dedup_collapses_duplicates():
    body = "indirect syscalls ntdll unhooking edr evasion"
    a = make_article(url="https://t.com/a", title="Story A", content=body)
    b = make_article(url="https://t.com/b", title="Story B", content=body)
    c = make_article(url="https://t.com/c", title="Unrelated", content="something else entirely")
    emb = HashingEmbedder(dim=256)
    pairs = [(1, a), (2, b), (3, c)]
    vecs = emb.embed([art.text_for_embedding() for _, art in pairs])
    embeddings = {pid: v for (pid, _), v in zip(pairs, vecs)}
    cluster_articles(pairs, embeddings, threshold=0.80)
    reps = representatives(pairs)
    assert len(reps) == 2


def test_ranking_and_selection(store):
    a1 = store.add_article(make_article(url="https://t.com/1", title="High"))
    a2 = store.add_article(make_article(url="https://t.com/2", title="Low"))
    store.save_score(a1, 8.0, "Tech", "good", "", False, "test", "v1")
    store.save_score(a2, 2.0, "Other", "meh", "", False, "test", "v1")
    rows = store.candidates(min_score=0, limit=10, drop_fluff=False)
    ranked = compute_ranks(rows)
    assert len(ranked) >= 2
    selected = select_top(ranked, min_score=5, top_n=10)
    assert len(selected) == 1
    assert selected[0][0]["id"] == a1
