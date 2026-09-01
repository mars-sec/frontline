"""Core data models used throughout the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Article:
    """Normalized article from a source adapter."""
    url: str
    title: str
    source: str
    published: str = ""
    summary: str = ""
    content: str = ""
    weight: float = 1.0
    source_type: str = "rss"

    cve_ids: list[str] = field(default_factory=list)
    actively_exploited: bool = False
    has_poc: bool = False

    cluster_id: str | None = None
    is_representative: bool = True
    also_covered_by: list[str] = field(default_factory=list)

    def text_for_scoring(self) -> str:
        return self.content or self.summary or ""

    def text_for_embedding(self) -> str:
        parts = [self.title]
        body = self.content or self.summary or ""
        if body:
            parts.append(body[:2000])
        return "\n".join(parts)


@dataclass
class Score:
    """LLM/heuristic judgment for a single article."""
    article_id: int
    score: float = 0.0
    section: str = "Other"
    reason: str = ""
    tldr: str = ""
    is_fluff: bool = False
    backend: str = ""
    model: str = ""
    rank: float | None = None


@dataclass
class Feedback:
    """User thumbs-up / thumbs-down on a scored article."""
    article_id: int
    vote: int  # +1 or -1
    reason: str = ""


@dataclass
class Edition:
    """A composed newspaper edition, output of the AI editor."""
    date: str
    editors_letter: str
    lead: EditionStory
    sections: list[EditionSection]
    article_ids: list[int] = field(default_factory=list)


@dataclass
class EditionStory:
    """One story as written by the AI editor."""
    article_id: int
    headline: str
    summary: str
    why_you_care: str
    url: str = ""
    source: str = ""
    published: str = ""


@dataclass
class EditionSection:
    """A section of the composed edition."""
    name: str
    stories: list[EditionStory]
