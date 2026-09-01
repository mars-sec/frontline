"""HTML-to-text and excerpt helpers."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")
_SENT = re.compile(r"(?<=[.!?])\s+")
_BLOCK = re.compile(
    r"</?(p|br|div|li|ul|ol|h[1-6]|tr|td|blockquote)[^>]*>",
    re.IGNORECASE,
)


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(value: str | None) -> str:
    """Flatten HTML/entities to a single clean line of text."""
    if not value:
        return ""
    spaced = _BLOCK.sub(" ", value)
    try:
        parser = _Stripper()
        parser.feed(spaced)
        text = parser.text()
    except Exception:
        text = _TAG.sub(" ", spaced)
    text = unescape(text)
    return _WS.sub(" ", text).strip()


def first_sentences(value: str | None, max_chars: int = 320,
                    max_sentences: int = 3) -> str:
    """Return the first few sentences, bounded by length."""
    text = html_to_text(value)
    if not text:
        return ""
    out = ""
    for sentence in _SENT.split(text)[:max_sentences]:
        if out and len(out) + len(sentence) + 1 > max_chars:
            break
        out = f"{out} {sentence}".strip()
    if not out:
        out = text
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + "…"
    return out
