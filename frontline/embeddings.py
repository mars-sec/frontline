"""Text embeddings: FastEmbed (preferred) or hashing fallback."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Protocol

import numpy as np

from .config import Settings

log = logging.getLogger("frontline.embeddings")

_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (mat / norms).astype(np.float32)


class HashingEmbedder:
    """Deterministic feature-hashing embedder. Offline-safe fallback."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _features(self, text: str) -> list[str]:
        text = text.lower()
        words = _TOKEN.findall(text)
        feats = list(words)
        joined = " ".join(words)
        feats += [joined[i:i + 3] for i in range(max(0, len(joined) - 2))]
        return feats

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for feat in self._features(text):
                h = int.from_bytes(
                    hashlib.md5(feat.encode()).digest()[:8], "little")
                idx = h % self.dim
                sign = 1.0 if (h >> 63) & 1 else -1.0
                out[row, idx] += sign
        return _l2_normalize(out)


class FastEmbedEmbedder:
    """Local ONNX embeddings via fastembed."""

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5",
                 dim: int = 384) -> None:
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=model)
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vecs = np.array(list(self._model.embed(texts)), dtype=np.float32)
        return _l2_normalize(vecs)


def get_embedder(settings: Settings) -> Embedder:
    """Build the configured embedder, falling back to hashing."""
    provider = settings.embeddings.provider
    dim = settings.embeddings.dim
    if provider == "fastembed":
        try:
            return FastEmbedEmbedder(
                model=settings.embeddings.model, dim=dim)
        except Exception as exc:
            log.warning("fastembed unavailable (%s); using hashing", exc)
    return HashingEmbedder(dim=dim)


def cosine_matrix(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity of one L2-normalized vector against a matrix."""
    if matrix.shape[0] == 0:
        return np.zeros((0,), dtype=np.float32)
    return matrix @ query.astype(np.float32)
