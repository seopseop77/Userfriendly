"""Tests for `llm_tracker_sdk.HookContext` (ADR-0012).

Pure SDK-level tests on the dataclass: how `request_text(level)`
degrades against the per-mode ceiling, and that the lazy
accessor handles the missing-body and bad-encoding edge cases.
"""

from __future__ import annotations

from llm_tracker_sdk import ContentLevel, HookContext


def _ctx(
    *,
    mode: str = "L",
    user_opted_in: bool = False,
    request_body: bytes | None = b"hello",
) -> HookContext:
    return HookContext(
        session_id="local",
        exchange_id="ex-1",
        mode=mode,
        user_opted_in=user_opted_in,
        _raw_request_body=request_body,
    )


def test_effective_ceiling_per_mode() -> None:
    assert _ctx(mode="L").effective_ceiling() == ContentLevel.L1
    assert _ctx(mode="A").effective_ceiling() == ContentLevel.L0
    assert _ctx(mode="R").effective_ceiling() == ContentLevel.L1


def test_effective_ceiling_lifts_only_in_mode_r_with_opt_in() -> None:
    """Mode R: opt-in lifts to L3; L and A unchanged."""
    assert _ctx(mode="L", user_opted_in=True).effective_ceiling() == ContentLevel.L1
    assert _ctx(mode="A", user_opted_in=True).effective_ceiling() == ContentLevel.L0
    assert _ctx(mode="R", user_opted_in=True).effective_ceiling() == ContentLevel.L3


def test_request_text_returns_body_when_within_ceiling() -> None:
    """Mode L allows up to L1; asking for L1 returns the body."""
    ctx = _ctx(mode="L", request_body=b"user message")
    assert ctx.request_text(ContentLevel.L1) == "user message"


def test_request_text_returns_none_when_degraded_to_l0() -> None:
    """Mode A's ceiling is L0; any requested level degrades to L0 → None."""
    assert _ctx(mode="A").request_text(ContentLevel.L3) is None
    assert _ctx(mode="A").request_text(ContentLevel.L1) is None


def test_request_text_returns_none_for_l0_request_in_any_mode() -> None:
    """Asking for L0 explicitly degrades to L0 even if the ceiling is higher."""
    assert _ctx(mode="L").request_text(ContentLevel.L0) is None
    assert _ctx(mode="R", user_opted_in=True).request_text(ContentLevel.L0) is None


def test_request_text_returns_body_in_mode_r_with_opt_in_at_l3() -> None:
    """Mode R + opt-in lifts the ceiling to L3 — full text is visible."""
    ctx = _ctx(mode="R", user_opted_in=True, request_body=b"raw text")
    assert ctx.request_text(ContentLevel.L3) == "raw text"


def test_request_text_caps_at_ceiling_in_mode_r_without_opt_in() -> None:
    """Mode R without opt-in caps at L1; asking for L3 returns text (not L0)."""
    ctx = _ctx(mode="R", user_opted_in=False, request_body=b"raw text")
    # L3 requested, ceiling is L1 → degrade to L1 → return text.
    assert ctx.request_text(ContentLevel.L3) == "raw text"


def test_request_text_returns_none_when_no_body() -> None:
    """No body (e.g. hook fires before forwarder reads body) → None."""
    assert _ctx(request_body=None).request_text(ContentLevel.L3) is None


def test_request_text_returns_none_for_invalid_utf8() -> None:
    """Binary body that isn't valid UTF-8 → None, not a UnicodeDecodeError."""
    ctx = _ctx(mode="L", request_body=b"\xff\xfe\x00")
    assert ctx.request_text(ContentLevel.L1) is None


def test_default_request_text_level_is_l3() -> None:
    """Calling `request_text()` with no arg defaults to L3 (degrades down)."""
    ctx = _ctx(mode="L", request_body=b"hi")
    assert ctx.request_text() == "hi"  # L3 → degrade to L1 → return text
