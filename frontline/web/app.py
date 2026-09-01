"""FastAPI dashboard and API endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from ..config import EDITIONS_DIR, load_settings
from ..store import Store

log = logging.getLogger("frontline.web")

HERE = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))

app = FastAPI(title="Frontline Dashboard")


@app.on_event("startup")
def _mount_editions():
    EDITIONS_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/editions", StaticFiles(directory=str(EDITIONS_DIR)),
              name="editions")


def _store() -> Store:
    return Store()


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    return dict(row)


# Dashboard page


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    settings = load_settings()
    return TEMPLATES.TemplateResponse(
        request, "dashboard.html",
        context={"paper_name": settings.paper_name},
    )


# API endpoints


@app.get("/api/stats")
async def api_stats():
    store = _store()
    settings = load_settings()
    editions = store.get_editions()
    scored = store.candidates(min_score=0, limit=1000,
                              window_days=settings.window_days,
                              drop_fluff=False)
    costs = store.costs_by_day()

    total_cost = sum(float(c["cost_usd"]) for c in costs)
    return {
        "edition_count": len(editions),
        "latest_edition": dict(editions[0]) if editions else None,
        "scored_count": len(scored),
        "total_cost_usd": round(total_cost, 4),
        "feedback_count": len(store.get_feedback(limit=10000)),
        "backend": settings.scoring_backend,
    }


@app.get("/api/editions")
async def api_editions():
    store = _store()
    editions = store.get_editions()
    return [_row_to_dict(e) for e in editions]


@app.get("/api/articles")
async def api_articles(limit: int = 50, min_score: float = 0):
    store = _store()
    settings = load_settings()
    rows = store.candidates(min_score=min_score, limit=limit,
                            window_days=settings.window_days,
                            drop_fluff=False)
    return [{
        "id": r["id"],
        "title": r["title"],
        "url": r["url"],
        "source": r["source"],
        "published": r["published"],
        "score": r["score"],
        "section": r["section"],
        "reason": r["reason"],
        "tldr": r["tldr"],
        "is_fluff": bool(r["is_fluff"]),
        "backend": r["backend"],
    } for r in rows]


@app.get("/api/feedback")
async def api_feedback(limit: int = 50):
    store = _store()
    rows = store.get_feedback(limit=limit)
    return [{
        "article_id": r["article_id"],
        "title": r["title"],
        "source": r["source"],
        "vote": r["vote"],
        "reason": r["reason"],
        "created_at": r["created_at"],
    } for r in rows]


@app.post("/api/feedback")
async def api_post_feedback(request: Request):
    body = await request.json()
    article_id = body.get("article_id")
    vote = body.get("vote")
    reason = body.get("reason", "")

    if article_id is None or vote not in (1, -1):
        return JSONResponse({"error": "article_id and vote (+1/-1) required"},
                            status_code=400)

    store = _store()
    row = store.get_article(article_id)
    if row is None:
        return JSONResponse({"error": "article not found"},
                            status_code=404)
    store.add_feedback(article_id, vote, reason)
    return {"ok": True, "article_id": article_id, "vote": vote}


@app.get("/api/costs")
async def api_costs():
    store = _store()
    rows = store.costs_by_day()
    return [{
        "day": r["day"],
        "stage": r["stage"],
        "model": r["model"],
        "input_tokens": r["input_tokens"],
        "output_tokens": r["output_tokens"],
        "cost_usd": round(float(r["cost_usd"]), 6),
        "calls": r["calls"],
    } for r in rows]
