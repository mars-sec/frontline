from tests.conftest import make_article


def test_add_article_returns_id(store):
    a = make_article(url="https://test.com/1")
    aid = store.add_article(a)
    assert aid is not None and isinstance(aid, int)


def test_add_article_dedup_by_url(store):
    a = make_article(url="https://test.com/dup")
    assert store.add_article(a) is not None
    assert store.add_article(a) is None


def test_add_article_dedup_by_title(store):
    a = make_article(url="https://test.com/1", title="Same Title")
    b = make_article(url="https://test.com/2", title="Same Title")
    assert store.add_article(a) is not None
    assert store.add_article(b) is None


def test_set_and_get_content(store):
    aid = store.add_article(make_article(content=""))
    store.set_content(aid, "Full body text.")
    row = store.get_article(aid)
    assert row["content"] == "Full body text."


def test_save_and_get_score(store):
    aid = store.add_article(make_article())
    store.save_score(aid, 7.5, "Tech", "reason", "tldr", False, "heuristic", "v1")
    score = store.get_score(aid)
    assert score["score"] == 7.5
    assert score["section"] == "Tech"


def test_feedback_roundtrip(store):
    aid = store.add_article(make_article())
    store.save_score(aid, 5.0, "Tech", "", "", False, "test", "v1")
    store.add_feedback(aid, 1, "liked it")
    store.add_feedback(aid, -1, "changed mind")
    fb = store.get_feedback(limit=10)
    assert len(fb) == 2
    assert fb[0]["vote"] == -1
    assert fb[1]["vote"] == 1


def test_usage_logging(store):
    store.log_usage("test", "model", False, 100, 50, 0, 0, 0.001)
    costs = store.costs_by_day()
    assert len(costs) == 1
    assert costs[0]["cost_usd"] == 0.001


def test_http_cache(store):
    store.set_http_cache("https://test.com/feed", etag="abc", last_modified="Wed")
    cache = store.get_http_cache("https://test.com/feed")
    assert cache["etag"] == "abc"
    assert cache["last_modified"] == "Wed"


def test_candidates_respects_min_score(store):
    a1 = store.add_article(make_article(url="https://t.com/1", title="High"))
    a2 = store.add_article(make_article(url="https://t.com/2", title="Low"))
    store.save_score(a1, 8.0, "Tech", "", "", False, "test", "v1")
    store.save_score(a2, 2.0, "Other", "", "", False, "test", "v1")
    high = store.candidates(min_score=5.0, limit=10, drop_fluff=False)
    assert len(high) == 1
    assert high[0]["id"] == a1


def test_edition_lifecycle(store):
    aid = store.add_article(make_article())
    store.save_score(aid, 7.0, "Tech", "", "", False, "test", "v1")
    store.save_edition("2026-08-30", "editions/2026-08-30.html")
    store.mark_published([aid], "2026-08-30")
    editions = store.get_editions()
    assert len(editions) == 1
    assert editions[0]["date"] == "2026-08-30"
    row = store.get_article(aid)
    assert row["edition_date"] == "2026-08-30"
