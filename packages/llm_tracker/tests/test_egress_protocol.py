"""Unit tests for the SDK egress surface (ADR-0015).

The SDK only ships the Protocol + the small dataclass + the exception type.
Implementation lives in `llm_tracker.egress_guard.client.HostEgressClient`,
covered by `packages/llm_tracker/tests/test_egress_client.py`.
"""

import inspect

from llm_tracker_sdk import (
    BasePlugin,
    EgressClient,
    EgressDenied,
    EgressResponse,
    HookContext,
)


def test_egress_response_is_frozen_dataclass():
    resp = EgressResponse(status_code=201, headers={"k": "v"}, body=b"ok")
    assert resp.status_code == 201
    assert resp.body == b"ok"

    # frozen=True per ADR-0015 surface; mutation must error.
    try:
        resp.status_code = 500  # type: ignore[misc]
    except Exception as exc:
        assert "frozen" in repr(exc).lower() or "FrozenInstance" in repr(type(exc))
    else:
        raise AssertionError("EgressResponse must be frozen")


def test_egress_denied_carries_url_and_reason():
    err = EgressDenied(url="https://x.test", reason="denied_by_egress_guard")
    assert err.url == "https://x.test"
    assert err.reason == "denied_by_egress_guard"
    # Message contains both for log readability.
    assert "https://x.test" in str(err)
    assert "denied_by_egress_guard" in str(err)


def test_egress_client_protocol_shape():
    """Pin the Protocol's `fetch` signature so changes require a deliberate
    SDK contract update (CLAUDE.md §10)."""
    sig = inspect.signature(EgressClient.fetch)
    params = sig.parameters
    assert "url" in params
    assert "method" in params and params["method"].default == "POST"
    assert "headers" in params and params["headers"].default is None
    assert "body" in params and params["body"].default is None
    assert "timeout" in params and params["timeout"].default == 30.0


def test_base_plugin_has_egress_field_default_none():
    """Plugins start with `egress=None`; the host populates it at load time."""

    class _P(BasePlugin):
        name = "p"

    p = _P()
    assert p.egress is None


def test_hook_context_has_egress_field_default_none():
    ctx = HookContext(session_id="s", exchange_id="x", mode="R")
    assert ctx.egress is None
