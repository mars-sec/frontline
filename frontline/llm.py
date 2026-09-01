"""Anthropic client wrapper with cost tracking and Batch API support."""

from __future__ import annotations

import logging
import os
import time

from .store import Store

log = logging.getLogger("frontline.llm")

# USD per million tokens (Claude API list prices, 2026-08).
# cache_read = 0.1x input; cache_write (5m TTL) = 1.25x input.
# Batch API = 0.5x on everything.
PRICES: dict[str, dict[str, float]] = {
    "claude-haiku-4-5":  {"in": 1.00, "out": 5.00},
    "claude-sonnet-5":   {"in": 2.00, "out": 10.00},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-opus-5":     {"in": 5.00, "out": 25.00},
    "claude-opus-4-8":   {"in": 5.00, "out": 25.00},
}


def _prices_for(model: str) -> dict[str, float] | None:
    if model in PRICES:
        return PRICES[model]
    for known in sorted(PRICES, key=len, reverse=True):
        if model.startswith(known):
            return PRICES[known]
    return None


def estimate_cost(model: str, usage, batch: bool = False) -> float:
    p = _prices_for(model)
    if p is None:
        return 0.0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cost = (
        usage.input_tokens * p["in"]
        + usage.output_tokens * p["out"]
        + cache_read * p["in"] * 0.1
        + cache_write * p["in"] * 1.25
    ) / 1_000_000
    return cost * 0.5 if batch else cost


class LLM:
    """Thin wrapper over the Anthropic SDK with usage logging and batch support."""

    def __init__(self, store: Store, poll_seconds: int = 20):
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "anthropic package not installed. "
                "Install with: pip install 'frontline[claude]'"
            )
        workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        headers = ({"anthropic-workspace-id": workspace_id}
                   if workspace_id else None)
        self.client = anthropic.Anthropic(default_headers=headers)
        self.store = store
        self.poll_seconds = poll_seconds

    def _log(self, stage: str, model: str, usage, batch: bool) -> None:
        self.store.log_usage(
            stage, model, batch,
            usage.input_tokens, usage.output_tokens,
            getattr(usage, "cache_read_input_tokens", 0) or 0,
            getattr(usage, "cache_creation_input_tokens", 0) or 0,
            estimate_cost(model, usage, batch),
        )
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        if cache_read:
            log.debug("cache hit: %d/%d input tokens from cache",
                      cache_read, usage.input_tokens)

    def create(self, stage: str, **params):
        """Synchronous Messages API call with usage logging."""
        response = self.client.messages.create(**params)
        self._log(stage, params["model"], response.usage, batch=False)
        return response

    def run_batch(self, stage: str, requests: list[dict]) -> dict[str, object]:
        """Submit or resume a batch, poll to completion, return {custom_id: Message}."""
        import anthropic

        batch_id = self.store.pending_batch(stage)
        if batch_id:
            log.info("resuming pending %s batch %s", stage, batch_id)
            try:
                self.client.messages.batches.retrieve(batch_id)
            except anthropic.NotFoundError:
                self.store.clear_pending_batch(stage)
                batch_id = None

        if not batch_id:
            batch = self.client.messages.batches.create(requests=requests)
            batch_id = batch.id
            self.store.set_pending_batch(stage, batch_id)
            log.info("submitted %s batch %s (%d requests), polling every %ds",
                     stage, batch_id, len(requests), self.poll_seconds)

        while True:
            batch = self.client.messages.batches.retrieve(batch_id)
            if batch.processing_status == "ended":
                break
            counts = batch.request_counts
            log.info("%s: %d processing, %d done, %d errored",
                     stage, counts.processing, counts.succeeded, counts.errored)
            time.sleep(self.poll_seconds)

        results: dict[str, object] = {}
        errored = 0
        first_error = None
        for result in self.client.messages.batches.results(batch_id):
            if result.result.type == "succeeded":
                message = result.result.message
                results[result.custom_id] = message
                self._log(stage, message.model, message.usage, batch=True)
            else:
                errored += 1
                if first_error is None and result.result.type == "errored":
                    first_error = result.result.error
        if errored:
            log.warning("%s: %d requests failed and were skipped", stage, errored)
            if first_error is not None:
                log.warning("first error: %s", first_error)
        self.store.clear_pending_batch(stage)
        return results


def text_of(message) -> str:
    """First text block of a response (structured outputs guarantee one)."""
    return next((b.text for b in message.content if b.type == "text"), "")


def tool_input_of(message, tool_name: str) -> dict | None:
    """Extract tool_use input from a response (for structured output via tools)."""
    for block in message.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input
    return None
