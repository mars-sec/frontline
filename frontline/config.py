"""Configuration loading: settings.yaml, sources.yaml, profile.md, .env."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
EDITIONS_DIR = ROOT / "editions"
LOGS_DIR = ROOT / "logs"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def load_env() -> None:
    """Load KEY=VALUE lines from .env in the project root.
    Real environment variables take precedence."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# Feed


@dataclass
class Feed:
    name: str
    url: str
    weight: float = 1.0
    type: str = "rss"
    enabled: bool = True


def load_feeds() -> list[Feed]:
    path = CONFIG_DIR / "sources.yaml"
    if not path.exists():
        print("No config/sources.yaml found. Add feeds or run "
              "`frontline discover`.", file=sys.stderr)
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    feeds = []
    for entry in raw.get("feeds", []):
        if not entry.get("url"):
            continue
        feeds.append(Feed(
            name=entry.get("name") or entry["url"],
            url=entry["url"],
            weight=float(entry.get("weight", 1.0)),
            type=entry.get("type", "rss"),
            enabled=entry.get("enabled", True),
        ))
    return feeds


def save_feeds(feeds: list[Feed]) -> None:
    path = CONFIG_DIR / "sources.yaml"
    data = {"feeds": []}
    for f in feeds:
        entry: dict = {"name": f.name, "url": f.url, "weight": f.weight}
        if f.type != "rss":
            entry["type"] = f.type
        if not f.enabled:
            entry["enabled"] = False
        data["feeds"].append(entry)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


# Settings


@dataclass
class PrefilterSettings:
    enabled: bool = True
    keep_fraction: float = 0.30
    min_candidates: int = 20
    max_llm_items: int = 300


@dataclass
class EmbeddingSettings:
    provider: str = "fastembed"
    model: str = "BAAI/bge-small-en-v1.5"
    dim: int = 384


@dataclass
class DedupSettings:
    similarity_threshold: float = 0.86


@dataclass
class WebSettings:
    host: str = "127.0.0.1"
    port: int = 8787


@dataclass
class LogSettings:
    console_level: str = "INFO"
    dir: str = "logs"
    keep_runs: int = 3
    trace_scoring: bool = True


@dataclass
class Settings:
    paper_name: str = "Frontline"
    scoring_backend: str = "claude"
    models: dict = field(default_factory=lambda: {
        "triage": "claude-haiku-4-5",
        "editor": "claude-sonnet-5",
        "discover": "claude-sonnet-5",
    })
    editor_fallback: str = "claude-haiku-4-5"
    ollama_model: str = "llama3.1:8b"
    use_batch: bool = True
    batch_poll_seconds: int = 20
    max_articles_per_feed: int = 25
    max_new_articles_per_run: int = 200
    article_clip_chars: int = 8000
    top_articles: int = 30
    min_score: float = 4
    min_articles: int = 5
    window_days: int = 10
    editor_clip_chars: int = 12000
    drop_fluff: bool = True
    sections: list = field(default_factory=lambda: [
        "Technology", "Science & Research", "Business & Economy",
        "Security", "World", "Culture & Ideas", "Your Projects",
    ])
    prefilter: PrefilterSettings = field(default_factory=PrefilterSettings)
    embeddings: EmbeddingSettings = field(default_factory=EmbeddingSettings)
    dedup: DedupSettings = field(default_factory=DedupSettings)
    web: WebSettings = field(default_factory=WebSettings)
    logging: LogSettings = field(default_factory=LogSettings)


_NESTED = {
    "prefilter": PrefilterSettings,
    "embeddings": EmbeddingSettings,
    "dedup": DedupSettings,
    "web": WebSettings,
    "logging": LogSettings,
}


def load_settings() -> Settings:
    path = CONFIG_DIR / "settings.yaml"
    if not path.exists():
        return Settings()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    s = Settings()
    for key, value in raw.items():
        if value is None:
            continue
        if key in _NESTED and isinstance(value, dict):
            nested = _NESTED[key]()
            for nk, nv in value.items():
                if hasattr(nested, nk) and nv is not None:
                    setattr(nested, nk, nv)
            setattr(s, key, nested)
        elif hasattr(s, key):
            setattr(s, key, value)
    return s


# Profile


def load_profile() -> str:
    profile = CONFIG_DIR / "profile.md"
    if profile.exists():
        return profile.read_text(encoding="utf-8")
    example = CONFIG_DIR / "profile.example.md"
    if example.exists():
        print("WARNING: config/profile.md not found, using "
              "profile.example.md.\nCopy it to config/profile.md and "
              "personalize it.", file=sys.stderr)
        return example.read_text(encoding="utf-8")
    raise SystemExit(
        "No profile found. Create config/profile.md.\n"
        "Start by copying config/profile.example.md."
    )
