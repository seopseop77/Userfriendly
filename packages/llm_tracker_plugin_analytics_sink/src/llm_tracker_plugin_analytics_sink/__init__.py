"""Server-side analytics sink plugin (ADR-0026 δ).

Reads `ctx.request_text()` + the parsed Anthropic system prompt on
`on_request_received`, then reads `ctx.response_usage()` and
`ctx.response_content_json()` on `on_persisted` (both populated by
the Option B SSE extractor wired through the forwarder) and writes
one row to the central server's `plugin_analytics` table.

The plugin owns its own async SQLAlchemy engine — the forwarder's
request-scoped session is unavailable inside `on_persisted` (the
hook fires *after* the forwarder's fresh post-stream session has
committed). The engine connects to ``LLMTRACK_DATABASE_URL`` with
``statement_cache_size=0`` to stay compatible with Supabase's
pgbouncer transaction mode (CP13-b finding).
"""

from .plugin import AnalyticsSink

__all__ = ["AnalyticsSink"]
