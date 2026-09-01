"""Scorer factory."""

from __future__ import annotations

from ..config import Settings
from ..store import Store
from .base import Scorer


def get_scorer(settings: Settings, store: Store) -> Scorer:
    backend = settings.scoring_backend
    if backend == "claude":
        from .claude import ClaudeScorer
        return ClaudeScorer(settings, store)
    elif backend == "ollama":
        from .ollama import OllamaScorer
        return OllamaScorer(settings, store)
    elif backend == "heuristic":
        from .heuristic import HeuristicScorer
        return HeuristicScorer(settings)
    else:
        raise ValueError(
            f"Unknown scoring_backend: {backend!r}. "
            f"Choose from: claude, ollama, heuristic"
        )
