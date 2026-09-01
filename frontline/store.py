"""SQLite persistence layer."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from .config import DATA_DIR
from .models import Article

SCHEMA = """\
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    url_hash TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    title_key TEXT DEFAULT '',
    source TEXT NOT NULL,
    source_type TEXT DEFAULT 'rss',
    published TEXT DEFAULT '',
    fetched_at TEXT NOT NULL,
    summary TEXT DEFAULT '',
    content TEXT DEFAULT '',
    weight REAL DEFAULT 1.0,
    cve_ids TEXT DEFAULT '',
    actively_exploited INTEGER DEFAULT 0,
    has_poc INTEGER DEFAULT 0,
    cluster_id TEXT,
    is_representative INTEGER DEFAULT 1,
    edition_date TEXT
);

CREATE TABLE IF NOT EXISTS scores (
    article_id INTEGER PRIMARY KEY REFERENCES articles(id),
    score REAL NOT NULL,
    section TEXT DEFAULT 'Other',
    reason TEXT DEFAULT '',
    tldr TEXT DEFAULT '',
    is_fluff INTEGER DEFAULT 0,
    backend TEXT DEFAULT '',
    model TEXT DEFAULT '',
    rank REAL
);

CREATE TABLE IF NOT EXISTS embeddings (
    article_id INTEGER PRIMARY KEY REFERENCES articles(id),
    vector BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id),
    vote INTEGER NOT NULL,
    reason TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS editions (
    date TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_batches (
    stage TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    stage TEXT NOT NULL,
    model TEXT NOT NULL,
    batch INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL,
    cache_write_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS http_cache (
    url_hash TEXT PRIMARY KEY,
    etag TEXT,
    last_modified TEXT,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_articles_title_key
    ON articles(title_key);
CREATE INDEX IF NOT EXISTS idx_articles_fetched
    ON articles(fetched_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().rstrip("/").encode("utf-8")).hexdigest()


_NONWORD = re.compile(r"[^a-z0-9]+")


def title_key(title: str) -> str:
    """Normalized headline for cross-source dedup."""
    return _NONWORD.sub(" ", (title or "").lower()).strip()


# Vector helpers


def _pack_vector(vec: np.ndarray) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec.astype(np.float32))


def _unpack_vector(blob: bytes) -> np.ndarray:
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


# Store


class Store:
    def __init__(self, db_path: Path | None = None):
        DATA_DIR.mkdir(exist_ok=True)
        self.conn = sqlite3.connect(db_path or DATA_DIR / "frontline.db")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r[1] for r in self.conn.execute(
            "PRAGMA table_info(articles)")}
        if "title_key" not in cols:
            self.conn.execute(
                "ALTER TABLE articles ADD COLUMN title_key TEXT DEFAULT ''")
        for row in self.conn.execute(
            "SELECT id, title FROM articles "
            "WHERE title_key IS NULL OR title_key = ''"
        ).fetchall():
            self.conn.execute(
                "UPDATE articles SET title_key = ? WHERE id = ?",
                (title_key(row["title"]), row["id"]))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # Articles

    def add_article(self, a: Article) -> int | None:
        """Insert if unseen (dedup by URL hash, then title key). Returns row ID or None."""
        uhash = url_hash(a.url)
        if self.conn.execute(
            "SELECT 1 FROM articles WHERE url_hash = ?", (uhash,)
        ).fetchone():
            return None

        tkey = title_key(a.title)
        if tkey and self.conn.execute(
            "SELECT 1 FROM articles WHERE title_key = ? LIMIT 1", (tkey,)
        ).fetchone():
            return None

        cur = self.conn.execute(
            "INSERT INTO articles "
            "(url, url_hash, title, title_key, source, source_type, "
            "published, fetched_at, summary, content, weight, "
            "cve_ids, actively_exploited, has_poc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (a.url, uhash, a.title, tkey, a.source, a.source_type,
             a.published, _now(), a.summary, a.content, a.weight,
             ",".join(a.cve_ids), int(a.actively_exploited),
             int(a.has_poc)),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_content(self, article_id: int, content: str) -> None:
        """Update full text if non-empty and not already set."""
        if not content:
            return
        self.conn.execute(
            "UPDATE articles SET content = ? WHERE id = ? "
            "AND (content IS NULL OR content = '')",
            (content, article_id))
        self.conn.commit()

    def get_article(self, article_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM articles WHERE id = ?", (article_id,)
        ).fetchone()

    def get_articles_since(self, since: datetime) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM articles WHERE fetched_at >= ? "
            "ORDER BY fetched_at DESC",
            (since.isoformat(),)
        ).fetchall()

    def untriaged(self, limit: int) -> list[sqlite3.Row]:
        """Articles with no score yet, newest first."""
        return self.conn.execute(
            "SELECT a.* FROM articles a "
            "LEFT JOIN scores s ON a.id = s.article_id "
            "WHERE s.article_id IS NULL "
            "ORDER BY a.fetched_at DESC LIMIT ?", (limit,)
        ).fetchall()

    def candidates(self, min_score: float, limit: int,
                   window_days: int = 3650,
                   drop_fluff: bool = True) -> list[sqlite3.Row]:
        """Best unpublished articles from the rolling window, weighted."""
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=window_days)).isoformat()
        return self.conn.execute(
            "SELECT a.*, s.score, s.section, s.reason, s.tldr, "
            "s.is_fluff, s.backend, s.model, s.rank, "
            "s.score * a.weight AS wscore "
            "FROM articles a JOIN scores s ON a.id = s.article_id "
            "WHERE a.edition_date IS NULL "
            "AND s.score * a.weight >= ? AND a.fetched_at >= ? "
            "AND (s.is_fluff = 0 OR ? = 0) "
            "ORDER BY wscore DESC, a.fetched_at DESC LIMIT ?",
            (min_score, cutoff, int(drop_fluff), limit),
        ).fetchall()

    def mark_published(self, article_ids: list[int],
                       edition_date: str) -> None:
        self.conn.executemany(
            "UPDATE articles SET edition_date = ? WHERE id = ?",
            [(edition_date, i) for i in article_ids],
        )
        self.conn.commit()

    def update_enrichment(self, article_id: int, cve_ids: list[str],
                          actively_exploited: bool,
                          has_poc: bool) -> None:
        self.conn.execute(
            "UPDATE articles SET cve_ids = ?, actively_exploited = ?, "
            "has_poc = ? WHERE id = ?",
            (",".join(cve_ids), int(actively_exploited),
             int(has_poc), article_id))
        self.conn.commit()

    def update_cluster(self, article_id: int, cluster_id: str | None,
                       is_representative: bool) -> None:
        self.conn.execute(
            "UPDATE articles SET cluster_id = ?, is_representative = ? "
            "WHERE id = ?",
            (cluster_id, int(is_representative), article_id))
        self.conn.commit()

    # Scores

    def save_score(self, article_id: int, score: float, section: str,
                   reason: str, tldr: str = "", is_fluff: bool = False,
                   backend: str = "", model: str = "") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO scores "
            "(article_id, score, section, reason, tldr, is_fluff, "
            "backend, model) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (article_id, score, section, reason, tldr,
             int(is_fluff), backend, model),
        )
        self.conn.commit()

    def save_rank(self, article_id: int, rank: float) -> None:
        self.conn.execute(
            "UPDATE scores SET rank = ? WHERE article_id = ?",
            (rank, article_id))
        self.conn.commit()

    def get_score(self, article_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM scores WHERE article_id = ?", (article_id,)
        ).fetchone()

    def delete_scores(self, article_ids: list[int]) -> int:
        """Clear scores for given articles (used by --rescore)."""
        self.conn.executemany(
            "DELETE FROM scores WHERE article_id = ?",
            [(i,) for i in article_ids])
        self.conn.commit()
        return len(article_ids)

    # Embeddings

    def save_embedding(self, article_id: int, vec: np.ndarray) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO embeddings (article_id, vector) "
            "VALUES (?, ?)", (article_id, _pack_vector(vec)))
        self.conn.commit()

    def get_embedding(self, article_id: int) -> np.ndarray | None:
        row = self.conn.execute(
            "SELECT vector FROM embeddings WHERE article_id = ?",
            (article_id,)).fetchone()
        return _unpack_vector(row["vector"]) if row else None

    def get_embeddings(self, article_ids: list[int]
                       ) -> dict[int, np.ndarray]:
        if not article_ids:
            return {}
        placeholders = ",".join("?" * len(article_ids))
        rows = self.conn.execute(
            f"SELECT article_id, vector FROM embeddings "
            f"WHERE article_id IN ({placeholders})", article_ids
        ).fetchall()
        return {r["article_id"]: _unpack_vector(r["vector"]) for r in rows}

    # Feedback

    def add_feedback(self, article_id: int, vote: int,
                     reason: str = "") -> None:
        self.conn.execute(
            "INSERT INTO feedback (article_id, vote, reason, created_at) "
            "VALUES (?, ?, ?, ?)",
            (article_id, vote, reason, _now()))
        self.conn.commit()

    def get_feedback(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT f.*, a.title, a.source, a.summary, a.content "
            "FROM feedback f JOIN articles a ON f.article_id = a.id "
            "ORDER BY f.created_at DESC LIMIT ?", (limit,)
        ).fetchall()

    # Editions

    def edition_exists(self, date: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM editions WHERE date = ?", (date,)
        ).fetchone() is not None

    def save_edition(self, date: str, path: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO editions (date, path, created_at) "
            "VALUES (?, ?, ?)", (date, path, _now()))
        self.conn.commit()

    def get_editions(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM editions ORDER BY date DESC"
        ).fetchall()

    # Batch resume

    def pending_batch(self, stage: str) -> str | None:
        row = self.conn.execute(
            "SELECT batch_id FROM pending_batches WHERE stage = ?",
            (stage,)).fetchone()
        return row["batch_id"] if row else None

    def set_pending_batch(self, stage: str, batch_id: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO pending_batches "
            "(stage, batch_id, created_at) VALUES (?, ?, ?)",
            (stage, batch_id, _now()))
        self.conn.commit()

    def clear_pending_batch(self, stage: str) -> None:
        self.conn.execute(
            "DELETE FROM pending_batches WHERE stage = ?", (stage,))
        self.conn.commit()

    # Usage ledger

    def log_usage(self, stage: str, model: str, batch: bool,
                  input_tokens: int, output_tokens: int,
                  cache_read: int, cache_write: int,
                  cost_usd: float) -> None:
        self.conn.execute(
            "INSERT INTO usage_log (ts, stage, model, batch, input_tokens, "
            "output_tokens, cache_read_tokens, cache_write_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), stage, model, int(batch), input_tokens, output_tokens,
             cache_read, cache_write, cost_usd))
        self.conn.commit()

    def costs_by_day(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT substr(ts, 1, 10) AS day, stage, model, "
            "SUM(input_tokens) AS input_tokens, "
            "SUM(output_tokens) AS output_tokens, "
            "SUM(cost_usd) AS cost_usd, COUNT(*) AS calls "
            "FROM usage_log GROUP BY day, stage, model "
            "ORDER BY day DESC"
        ).fetchall()

    # HTTP cache

    def get_http_cache(self, url: str) -> dict | None:
        row = self.conn.execute(
            "SELECT etag, last_modified FROM http_cache "
            "WHERE url_hash = ?", (url_hash(url),)
        ).fetchone()
        if not row:
            return None
        return {"etag": row["etag"], "last_modified": row["last_modified"]}

    def set_http_cache(self, url: str, etag: str | None = None,
                       last_modified: str | None = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO http_cache "
            "(url_hash, etag, last_modified, fetched_at) "
            "VALUES (?, ?, ?, ?)",
            (url_hash(url), etag, last_modified, _now()))
        self.conn.commit()
