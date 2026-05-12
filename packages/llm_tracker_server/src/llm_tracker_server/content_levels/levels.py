"""Re-export of the SDK content-level primitives (design.md §7.1).

ADR-0019 retired the L/A/R deployment-mode taxonomy; the L0--L3 ladder
survives as a per-plugin clamping primitive that CP10's
``min_content_level`` manifest field will wire. For CP8 the server-side
host still hands a permissive context to plugins; the levels primitives
are imported here so future call sites can route through the
``llm_tracker_server.content_levels`` namespace instead of reaching
across into the SDK package directly.
"""

from __future__ import annotations

from llm_tracker_sdk.levels import ContentLevel, degrade, effective_ceiling

__all__ = ["ContentLevel", "degrade", "effective_ceiling"]
