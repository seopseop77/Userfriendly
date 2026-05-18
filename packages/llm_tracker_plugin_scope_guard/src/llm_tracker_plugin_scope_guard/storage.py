"""Persistence — ``scope_chunks`` reads and ``scope_alerts`` writes (ADR-0030 §D7/§D8).

Stub for CP2. CP5 implements:

- ``read_chunks(engine, org_id)`` and the max-cosine query using
  pgvector's ``<=>`` operator; one row return per evaluation.
- ``insert_alert(engine, ...)`` writing a single ``scope_alerts`` row
  with the four ADR-0030 §Axis 6 columns (``stage``, ``stage2_verdict``,
  ``stage2_reason``, ``matched_chunk_id``).
- Engine owned by the plugin (analytics_sink pattern); shared
  ``LLMTRACK_DATABASE_URL`` with ``statement_cache_size=0`` for the
  Supabase pgbouncer transaction-mode quirk.
"""

from __future__ import annotations
