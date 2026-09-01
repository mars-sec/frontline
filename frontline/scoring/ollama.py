"""Ollama scorer: local LLMs with JSON mode."""

from __future__ import annotations

import json
import logging

from ..config import Settings, load_profile
from ..models import Article, Score
from ..store import Store
from .base import build_system_prompt, build_user_prompt, parse_judgment
from .fewshot import build_fewshot

log = logging.getLogger("frontline.scoring.ollama")


class OllamaScorer:
    name = "ollama"

    def __init__(self, settings: Settings, store: Store):
        try:
            import ollama as _ollama
        except ImportError:
            raise RuntimeError(
                "ollama package not installed. "
                "Install with: pip install 'frontline[ollama]'"
            )
        self.settings = settings
        self.store = store
        self.model = settings.ollama_model
        self._ollama = _ollama
        self._profile = load_profile()
        self._fewshot = build_fewshot(store)
        self._system_prompt = build_system_prompt(
            self._profile, settings.sections, self._fewshot,
        )

    def score(self, article_id: int, article: Article) -> Score:
        user_msg = build_user_prompt(article)
        try:
            resp = self._ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                format="json",
            )
            text = resp.get("message", {}).get("content", "")
        except Exception:
            log.warning("ollama call failed for article %d", article_id,
                        exc_info=True)
            text = ""
        return parse_judgment(text, article_id, "ollama", self.model)
