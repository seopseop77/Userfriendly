"""Upstream-response extractors (ADR-0026 Option B).

One module per upstream provider. The forwarder consumes the SSE
stream and hands raw bytes to the extractor via an asyncio.Queue;
the extractor produces a `ParsedResponse` that the forwarder stores
on the per-exchange `HookContext` so plugins read structured data
via `response_usage()` / `response_content_json()`.

Extractors must never raise. Missing fields stay `None` per ADR-0027
axis 1 ("best-effort NULL").
"""

from .anthropic import ParsedResponse, ResponseUsage, parse_sse_stream

__all__ = ["ParsedResponse", "ResponseUsage", "parse_sse_stream"]
