import pytest

from tests.conftest import make_article

from frontline.web.app import app


@pytest.fixture()
def client(store, monkeypatch):
    monkeypatch.setattr("frontline.web.app._store", lambda: store)
    from starlette.testclient import TestClient
    return TestClient(app)


@pytest.fixture()
def seeded_store(store):
    a1 = store.add_article(make_article(url="https://t.com/1", title="Art 1"))
    a2 = store.add_article(make_article(url="https://t.com/2", title="Art 2"))
    store.save_score(a1, 8.0, "Tech", "good", "tldr", False, "test", "v1")
    store.save_score(a2, 5.0, "Other", "ok", "", False, "test", "v1")
    store.add_feedback(a1, 1, "liked")
    store.log_usage("test", "model", False, 100, 50, 0, 0, 0.01)
    store.save_edition("2026-08-30", "editions/2026-08-30.html")
    return store


def test_dashboard_page(client, seeded_store):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Dashboard" in resp.text


def test_api_stats(client, seeded_store):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["edition_count"] >= 1
    assert "backend" in data


def test_api_articles(client, seeded_store):
    resp = client.get("/api/articles?limit=10&min_score=0")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_editions(client, seeded_store):
    resp = client.get("/api/editions")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_api_feedback_get(client, seeded_store):
    resp = client.get("/api/feedback")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    assert items[0]["vote"] == 1


def test_api_feedback_post_valid(client, seeded_store):
    articles = client.get("/api/articles?limit=1&min_score=0").json()
    if articles:
        aid = articles[0]["id"]
        resp = client.post("/api/feedback",
                           json={"article_id": aid, "vote": -1})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


def test_api_feedback_post_invalid(client, seeded_store):
    resp = client.post("/api/feedback",
                       json={"article_id": 1, "vote": 5})
    assert resp.status_code == 400


def test_api_feedback_post_not_found(client, seeded_store):
    resp = client.post("/api/feedback",
                       json={"article_id": 99999, "vote": 1})
    assert resp.status_code == 404


def test_api_costs(client, seeded_store):
    resp = client.get("/api/costs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert "cost_usd" in data[0]
