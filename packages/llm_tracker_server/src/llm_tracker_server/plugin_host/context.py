"""Server-side :class:`HookContext` construction.

The SDK's :class:`~llm_tracker_sdk.hook_context.HookContext` dataclass
still encodes the legacy L/A/R-mode ceiling table from the local
sidecar (its ``effective_ceiling`` reads ``mode`` and
``user_opted_in``). ADR-0019 retired those modes, so the server-side
host constructs every context with the most permissive pair
(``mode="R"``, ``user_opted_in=True``), which yields an L3 ceiling
under the SDK's current table.

This is a **transitional shape** that lands with CP8. CP10 introduces
the ``min_content_level`` manifest field and per-plugin clamping at
dispatch time; once that lands, the server-side host will clamp each
plugin's view of the context to its declared level regardless of what
the SDK's mode-based ceiling returns. Documented in the plan worklog
under §Decisions §CP8.

The factory is the single chokepoint where the placeholder mode/opt-in
pair lives so CP10's swap-out is one diff, not a sweep.
"""

from __future__ import annotations

from llm_tracker_sdk import HookContext

# CP8 transitional placeholders. CP10 will replace the call site with a
# manifest-driven `_ceiling` slot (or an SDK-level overhaul of the
# ceiling resolution). Until then, "R" + opted-in yields L3 -- the
# permissive shape every existing plugin already expects from the
# local-sidecar host's default behaviour.
_PLACEHOLDER_MODE = "R"
_PLACEHOLDER_OPT_IN = True


def make_hook_context(
    *,
    session_id: str,
    exchange_id: str,
    request_body: bytes | None = None,
) -> HookContext:
    """Build a per-exchange :class:`HookContext` with permissive defaults.

    ``session_id`` is the local-sidecar's per-exchange grouping key;
    the server-side host has no equivalent yet (one CLI process = one
    session), so the caller passes a stable string -- ``"server"`` for
    production wiring, ``"local"`` in tests that want to match the
    legacy shape.
    """
    return HookContext(
        session_id=session_id,
        exchange_id=exchange_id,
        mode=_PLACEHOLDER_MODE,
        user_opted_in=_PLACEHOLDER_OPT_IN,
        _raw_request_body=request_body,
    )
