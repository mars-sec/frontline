"""Shared pytest fixtures for Frontline tests."""

import os
import shutil

import pytest

os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from frontline.config import load_settings
from frontline.models import Article
from frontline.store import Store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Fresh store using a temp directory, cross-thread safe for web tests."""
    db_path = tmp_path / "data"
    db_path.mkdir()
    monkeypatch.setattr("frontline.store.DATA_DIR", db_path)
    s = Store()
    s.conn.close()
    import sqlite3
    db_file = db_path / "frontline.db"
    s.conn = sqlite3.connect(str(db_file), check_same_thread=False)
    s.conn.row_factory = sqlite3.Row
    yield s
    s.conn.close()


@pytest.fixture()
def settings():
    return load_settings()


def make_article(**overrides) -> Article:
    defaults = dict(
        url="https://example.com/article",
        title="Test Article",
        source="TestBlog",
        summary="A test article summary.",
        content="Full text body of the test article.",
        weight=1.0,
    )
    defaults.update(overrides)
    return Article(**defaults)
