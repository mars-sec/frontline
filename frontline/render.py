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
    """Copy the latest edition as index.html and generate archive.html."""
    EDITIONS_DIR.mkdir(parents=True, exist_ok=True)
    editions = store.get_editions()
    if not editions:
        return EDITIONS_DIR / "index.html"
    latest = EDITIONS_DIR / f"{editions[0]['date']}.html"
    out = EDITIONS_DIR / "index.html"
    if latest.exists():
        out.write_text(latest.read_text(encoding="utf-8"), encoding="utf-8")
    env = _env()
    archive = env.get_template("index.html.j2").render(
        paper_name=settings.paper_name,
        editions=[dict(e) for e in editions],
    )
    (EDITIONS_DIR / "archive.html").write_text(archive, encoding="utf-8")
    return out
