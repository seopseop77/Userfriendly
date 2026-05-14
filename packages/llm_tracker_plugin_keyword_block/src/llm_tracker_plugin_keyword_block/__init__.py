"""Keyword-block plugin — server-side request gate.

Returns `Block(...)` from `on_request_received` when the raw request
body contains any keyword from the configured list (case-insensitive).
The list is read from `LLMTRACK_KEYWORD_BLOCK_LIST` (comma-separated)
at construction time; absent or empty → no keywords → the plugin
loads but never blocks.

This was originally a TEST-ONLY artefact for the Block lifecycle
under the local-sidecar host. It now ships in the central server's
Docker image alongside `analytics_sink` as a small, operator-
configurable content gate. The Phase-1c `scope_guard` plugin remains
the proper full-scale content-policy surface.
"""

from __future__ import annotations

import os

from llm_tracker_sdk import BasePlugin, Block, ContentLevel, HookContext, Pass

KEYWORD_BLOCK_LIST_ENV = "LLMTRACK_KEYWORD_BLOCK_LIST"
# Empty default: plugin loads but never blocks unless the operator
# supplies a non-empty list via the env var.
DEFAULT_KEYWORDS: tuple[str, ...] = ()


def _load_keywords() -> tuple[str, ...]:
    raw = os.environ.get(KEYWORD_BLOCK_LIST_ENV)
    if raw is None:
        return DEFAULT_KEYWORDS
    parsed = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    return parsed or DEFAULT_KEYWORDS


class KeywordBlockPlugin(BasePlugin):
    """Block any request whose body contains a forbidden keyword."""

    name = "keyword_block"

    def __init__(self, keywords: tuple[str, ...] | None = None) -> None:
        if keywords is None:
            keywords = _load_keywords()
        # Normalise once; keyword matching is case-insensitive.
        self._keywords: tuple[str, ...] = tuple(k.lower() for k in keywords if k)

    async def on_request_received(self, exchange_id: str, ctx: HookContext) -> Pass | Block:
        if not self._keywords:
            return Pass()
        # Ask for raw text. The host degrades to whatever the mode allows;
        # we treat None (degraded to L0, no body, or non-UTF-8) as "no
        # signal, let it through" rather than blocking blindly.
        body = ctx.request_text(ContentLevel.L3)
        if body is None:
            return Pass()
        haystack = body.lower()
        for keyword in self._keywords:
            if keyword in haystack:
                return Block(reason=f"contains forbidden keyword: {keyword!r}")
        return Pass()


__all__ = ["DEFAULT_KEYWORDS", "KEYWORD_BLOCK_LIST_ENV", "KeywordBlockPlugin"]
