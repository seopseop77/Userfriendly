"""Server-side task-scope monitor plugin (ADR-0030; provider rev ADR-0031).

On ``on_persisted``, the plugin:

1. Extracts user-initiated turn text from ``ctx.request_text()`` (ADR-0026
   accessor + ADR-0029 scrubber).
2. Embeds it via Gemini ``text-embedding-004`` through
   ``HostEgressClient``.
3. Runs a max-cosine query against the org's ``scope_chunks`` (pgvector
   ``<=>`` operator).
4. If the max similarity falls in the operator-tunable ambiguous band,
   routes to a Stage-2 ``gemini-2.5-flash`` judge.
5. Writes one row to ``scope_alerts`` with the stage, verdict, reason,
   and matched chunk id.

The plugin is observe-only: it never returns ``Block(...)``. ADR-0030
§Deferred §1 keeps the real-time blocking path as an additive follow-up
once threshold stability data accumulates.
"""

from .plugin import ScopeGuard

__all__ = ["ScopeGuard"]
