from tests.conftest import make_article

from frontline.editor import compose_edition, _resolve_edition
from frontline.models import Edition


def test_resolve_edition_builds_model(store):
    a1 = store.add_article(make_article(url="https://t.com/1", title="Lead"))
    a2 = store.add_article(make_article(url="https://t.com/2", title="Story2"))
    store.save_score(a1, 8.0, "Tech", "", "", False, "test", "v1")
    store.save_score(a2, 6.0, "Science", "", "", False, "test", "v1")

    data = {
        "editors_letter": "Hello readers",
        "lead": {"article_id": a1, "headline": "H1", "summary": "S1",
                 "why_you_care": "W1"},
        "sections": [{"name": "Sec", "stories": [
            {"article_id": a2, "headline": "H2", "summary": "S2",
             "why_you_care": "W2"},
        ]}],
    }

    rows = store.candidates(min_score=0, limit=10, drop_fluff=False)
    edition = _resolve_edition(data, rows, store)
    assert isinstance(edition, Edition)
    assert edition.lead.article_id == a1
    assert len(edition.sections) == 1
    assert edition.article_ids == [a1, a2]


def test_resolve_edition_falls_back_on_bad_lead(store):
    a1 = store.add_article(make_article(url="https://t.com/1", title="First"))
    store.save_score(a1, 8.0, "Tech", "", "", False, "test", "v1")
    rows = store.candidates(min_score=0, limit=10, drop_fluff=False)

    data = {
        "editors_letter": "Hi",
        "lead": {"article_id": 99999, "headline": "X", "summary": "X",
                 "why_you_care": "X"},
        "sections": [],
    }
    edition = _resolve_edition(data, rows, store)
    assert edition.lead.article_id == a1


def test_heuristic_compose(store, settings):
    a1 = store.add_article(make_article(url="https://t.com/1", title="Top"))
    a2 = store.add_article(make_article(url="https://t.com/2", title="Second"))
    store.save_score(a1, 8.0, "Tech", "good", "tldr", False, "test", "v1")
    store.save_score(a2, 6.0, "Science", "ok", "sum", False, "test", "v1")
    settings.scoring_backend = "heuristic"
    edition = compose_edition(store, settings)
    assert edition is not None
    assert edition.lead is not None
    assert len(edition.article_ids) >= 1


def test_compose_returns_none_when_empty(store, settings):
    settings.scoring_backend = "heuristic"
    edition = compose_edition(store, settings)
    assert edition is None
