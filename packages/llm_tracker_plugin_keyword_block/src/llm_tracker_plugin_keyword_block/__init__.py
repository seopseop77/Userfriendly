"""TEST-ONLY keyword-block plugin.

Returns `Block(...)` from `on_request_received` if the raw request body
contains any keyword from the configured list (case-insensitive). The
list is whatever `LLMTRACK_KEYWORDS_BLOCK_LIST` (comma-separated) holds
at construction time, falling back to a tiny built-in default that's
just enough to exercise the block path manually.

This is a verification artefact for the Block lifecycle. The real
content-policy plugin is Phase-1c `scope_guard`; delete this once that
lands. See `docs/worklog/2026-05-06-test-plugins.md`.
"""

from __future__ import annotations

import os

from llm_tracker_sdk import BasePlugin, Block, ContentLevel, HookContext, Pass

DEFAULT_KEYWORDS: tuple[str, ...] = ("forbidden_word", "do_not_send")
KEYWORDS_ENV = "LLMTRACK_KEYWORDS_BLOCK_LIST"


def _load_keywords() -> tuple[str, ...]:
    raw = os.environ.get(KEYWORDS_ENV)
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


__all__ = ["DEFAULT_KEYWORDS", "KEYWORDS_ENV", "KeywordBlockPlugin"]
