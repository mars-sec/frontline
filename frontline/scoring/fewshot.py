"""Build few-shot examples from user feedback for scoring prompts."""

from __future__ import annotations

from ..store import Store


def build_fewshot(store: Store, max_examples: int = 6) -> str:
    """Return a prompt fragment with recent feedback as few-shot examples."""
    rows = store.get_feedback(limit=max_examples * 2)
    if not rows:
        return ""

    positives = [r for r in rows if r["vote"] > 0][:max_examples // 2]
    negatives = [r for r in rows if r["vote"] < 0][:max_examples // 2]
    examples = positives + negatives
    if not examples:
        return ""

    lines = ["Calibration examples from past reader feedback:"]
    for row in examples:
        label = "LIKED" if row["vote"] > 0 else "DISLIKED"
        row_reason = row["reason"] if row["reason"] else ""
        reason = f" - {row_reason}" if row_reason else ""
        lines.append(
            f"- [{label}] \"{row['title']}\" from {row['source']}{reason}"
        )
    lines.append("")
    return "\n".join(lines)
