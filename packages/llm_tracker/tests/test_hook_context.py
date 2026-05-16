"""Tests for `llm_tracker_sdk.HookContext` (ADR-0012, design.md §7.1).

Pure SDK-level tests on the dataclass. Two surfaces:

- `request_text(level)` degrades against the per-mode ceiling and is
  only non-None at effective L2 / L3.
- `request_hash()` / `request_length()` are the L1 escape hatch:
  populated whenever `effective_ceiling() >= L1`, `None` otherwise.
"""

from __future__ import annotations

import hashlib

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


# -- effective_ceiling ----------------------------------------------------


def test_effective_ceiling_per_mode() -> None:
    assert _ctx(mode="L").effective_ceiling() == ContentLevel.L1
    assert _ctx(mode="A").effective_ceiling() == ContentLevel.L0
    assert _ctx(mode="R").effective_ceiling() == ContentLevel.L1


def test_effective_ceiling_lifts_only_in_mode_r_with_opt_in() -> None:
    """Mode R: opt-in lifts to L3; L and A unchanged."""
    assert _ctx(mode="L", user_opted_in=True).effective_ceiling() == ContentLevel.L1
    assert _ctx(mode="A", user_opted_in=True).effective_ceiling() == ContentLevel.L0
    assert _ctx(mode="R", user_opted_in=True).effective_ceiling() == ContentLevel.L3


# -- request_text ---------------------------------------------------------


def test_request_text_returns_none_at_l1_ceiling() -> None:
    """Mode L caps at L1; request_text(L1) returns None — use request_hash()."""
    ctx = _ctx(mode="L", request_body=b"user message")
    assert ctx.request_text(ContentLevel.L1) is None
    # Asking for L3 still degrades to L1 → None.
    assert ctx.request_text(ContentLevel.L3) is None


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


def test_request_text_returns_body_at_l2_when_ceiling_allows() -> None:
    """L2 today returns raw text (scrubbing deferred to Phase 1c).

    Pinning the current shape so the Phase 1c switch to scrubbed
    output is a deliberate, test-visible change.
    """
    ctx = _ctx(mode="R", user_opted_in=True, request_body=b"raw text")
    assert ctx.request_text(ContentLevel.L2) == "raw text"


def test_request_text_returns_none_when_no_body() -> None:
    """No body (e.g. hook fires before forwarder reads body) → None."""
    assert _ctx(request_body=None).request_text(ContentLevel.L3) is None


def test_request_text_returns_none_for_invalid_utf8() -> None:
    """Binary body that isn't valid UTF-8 → None at L3, not a UnicodeDecodeError."""
    ctx = _ctx(mode="R", user_opted_in=True, request_body=b"\xff\xfe\x00")
    assert ctx.request_text(ContentLevel.L3) is None


def test_default_request_text_level_is_l3() -> None:
    """Calling `request_text()` with no arg defaults to L3 (degrades down)."""
    ctx = _ctx(mode="R", user_opted_in=True, request_body=b"hi")
    assert ctx.request_text() == "hi"


# -- request_hash / request_length ---------------------------------------


def test_request_hash_and_length_return_none_at_l0_ceiling() -> None:
    """Mode A's ceiling is L0; even hashes are denied."""
    ctx = _ctx(mode="A", request_body=b"hello")
    assert ctx.request_hash() is None
    assert ctx.request_length() is None


def test_request_hash_and_length_populated_at_l1_ceiling() -> None:
    """Mode L caps at L1; hash and length are the L1 escape hatch."""
    body = b"user message"
    ctx = _ctx(mode="L", request_body=body)
    assert ctx.request_hash() == hashlib.sha256(body).hexdigest()
    assert ctx.request_length() == len(body)


def test_request_hash_and_length_populated_at_l3_ceiling() -> None:
    """Mode R + opt-in lifts to L3; hash and length still populated."""
    body = b"deep raw text"
    ctx = _ctx(mode="R", user_opted_in=True, request_body=body)
    assert ctx.request_hash() == hashlib.sha256(body).hexdigest()
    assert ctx.request_length() == len(body)


def test_request_hash_and_length_return_none_when_no_body() -> None:
    """No body → hash and length are None even at high ceilings."""
    ctx = _ctx(mode="R", user_opted_in=True, request_body=None)
    assert ctx.request_hash() is None
    assert ctx.request_length() is None


def test_request_hash_handles_non_utf8_body() -> None:
    """SHA-256 is over raw bytes; non-UTF-8 must hash without raising."""
    body = b"\xff\xfe\x00"
    ctx = _ctx(mode="L", request_body=body)
    assert ctx.request_hash() == hashlib.sha256(body).hexdigest()
    assert ctx.request_length() == 3


# -- ADR-0029: accessor-level scrubbing ----------------------------------


def test_request_text_redacts_secrets_at_l3() -> None:
    """`request_text()` runs the scrubber before returning (ADR-0029).

    Raw bytes on `_raw_request_body` stay untouched so the storage layer
    keeps the canonical body; only what the plugin reads is redacted.
    """
    body = b'{"prompt":"call ANTHROPIC_API_KEY=sk-ant-api03-AbCdEfGhIj now"}'
    ctx = _ctx(mode="R", user_opted_in=True, request_body=body)
    out = ctx.request_text(ContentLevel.L3)
    assert out is not None
    assert "sk-ant-api03" not in out
    assert "[REDACTED:secret]" in out
    # Hash + length still report against the canonical bytes.
    assert ctx.request_hash() == hashlib.sha256(body).hexdigest()
    assert ctx.request_length() == len(body)
    # Canonical bytes preserved on the dataclass.
    assert ctx._raw_request_body == body


def test_request_text_redacts_email_at_l2() -> None:
    """Scrubbing fires at every level that returns text (L2 + L3)."""
    body = b"contact me at alice@example.com"
    ctx = _ctx(mode="R", user_opted_in=True, request_body=body)
    assert ctx.request_text(ContentLevel.L2) == ("contact me at [REDACTED:email]")


def test_response_content_json_redacts_secrets() -> None:
    """`response_content_json()` runs the scrubber before returning."""

    class _Stub:
        response_json = '{"content":[{"type":"text","text":"token Bearer xyz.abc-123"}]}'

    ctx = HookContext(
        session_id="local",
        exchange_id="ex-1",
        mode="R",
        user_opted_in=True,
        _parsed_response=_Stub(),
    )
    out = ctx.response_content_json()
    assert out is not None
    assert "xyz.abc-123" not in out
    assert "[REDACTED:bearer]" in out
    # Canonical JSON string preserved on the parsed response.
    assert "xyz.abc-123" in _Stub.response_json


def test_response_content_json_returns_none_when_not_parsed() -> None:
    """Without `_parsed_response` the accessor still short-circuits to None."""
    ctx = HookContext(
        session_id="local",
        exchange_id="ex-1",
        mode="R",
        user_opted_in=True,
    )
    assert ctx.response_content_json() is None
