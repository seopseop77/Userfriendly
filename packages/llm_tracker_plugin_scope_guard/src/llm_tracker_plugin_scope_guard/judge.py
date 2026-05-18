"""Stage-2 LLM judge — OpenAI ``gpt-4o-mini`` (ADR-0030 §D4).

Stub for CP2. CP4 implements the judge:

- Egress via the same :class:`HostEgressClient` as
  :mod:`.embeddings`, target
  ``https://api.openai.com/v1/chat/completions``.
- Frozen prompt template pinned as a module-top string per ADR-0030 §Q4
  (the exact wording must be diff-visible for future tweaks).
- Returns ``(verdict: str, reason: str)`` for the ``scope_alerts.stage2_*``
  columns; verdict is one of ``"in_scope"`` / ``"out_of_scope"``.
"""

from __future__ import annotations
