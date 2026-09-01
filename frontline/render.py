"""Render an Edition to a broadsheet HTML page and archive index."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import EDITIONS_DIR, Settings
from .models import Edition
from .store import Store

log = logging.getLogger("frontline.render")

TEMPLATES = Path(__file__).resolve().parent / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
    )


def render_edition(store: Store, settings: Settings, edition: Edition,
                   edition_date: str) -> Path:
    """Render edition HTML and update the archive index."""
    EDITIONS_DIR.mkdir(parents=True, exist_ok=True)
    env = _env()
    pretty_date = date.fromisoformat(edition_date).strftime("%A, %B %d, %Y")
    html = env.get_template("edition.html.j2").render(
        paper_name=settings.paper_name,
        date=edition_date,
        pretty_date=pretty_date,
        edition=edition,
    )
    out = EDITIONS_DIR / f"{edition_date}.html"
    out.write_text(html, encoding="utf-8")
    store.save_edition(edition_date, str(out))
    store.mark_published(edition.article_ids, edition_date)
    render_index(store, settings)
    log.info("rendered edition: %s", out)
    return out


def render_index(store: Store, settings: Settings) -> Path:
    """Render the archive index page."""
    EDITIONS_DIR.mkdir(parents=True, exist_ok=True)
    env = _env()
    editions = store.get_editions()
    html = env.get_template("index.html.j2").render(
        paper_name=settings.paper_name,
        editions=[dict(e) for e in editions],
    )
    out = EDITIONS_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    return out
