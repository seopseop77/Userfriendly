"""Server-side :class:`HookContext` construction (ADR-0019 §Open questions).

The SDK's :class:`~llm_tracker_sdk.hook_context.HookContext` keeps the
legacy mode/opt-in fields for the local-sidecar path. The server-side
host bypasses that math: each context is built with a manifest-driven
``_ceiling`` set per plugin at dispatch time. The placeholder
``mode="R"`` / ``user_opted_in=True`` pair is retained only as filler
for the dataclass's required ``mode`` field and is not consulted by
``HookContext.effective_ceiling`` once ``_ceiling`` is set.

CP10 wires the manifest's ``min_content_level`` field through this
factory; :class:`~llm_tracker_server.plugin_host.host.PluginHost`
re-points ``ctx._ceiling`` per plugin in each dispatch loop, similar
to how ``ctx.egress`` is re-pointed per plugin (ADR-0015).
"""

from __future__ import annotations

from llm_tracker_sdk import ContentLevel, HookContext

# Filler for the SDK dataclass's required ``mode`` field; never consulted
# at runtime because the host always sets ``_ceiling`` before any plugin
# reads the context.
_PLACEHOLDER_MODE = "R"
_PLACEHOLDER_OPT_IN = True


def make_hook_context(
    *,
    session_id: str,
    exchange_id: str,
    request_body: bytes | None = None,
    min_content_level: ContentLevel | None = None,
) -> HookContext:
    """Build a per-exchange :class:`HookContext`.

    ``min_content_level`` pins :attr:`HookContext._ceiling` so the
    plugin-visible accessors are clamped to the declared level
    regardless of the SDK's mode-based math. When omitted the context
    is built without a clamp; the dispatch loop re-points it per plugin
    before any hook runs, so this default is only observable in unit
    tests that construct contexts outside the dispatch path.
    """
    return HookContext(
        session_id=session_id,
        exchange_id=exchange_id,
        mode=_PLACEHOLDER_MODE,
        user_opted_in=_PLACEHOLDER_OPT_IN,
        _raw_request_body=request_body,
        _ceiling=min_content_level,
    )
