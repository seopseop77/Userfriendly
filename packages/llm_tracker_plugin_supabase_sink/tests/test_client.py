"""Unit tests for `SupabaseSinkClient` (the vendor-coupled write surface).

`HostEgressClient` itself is covered by
`packages/llm_tracker/tests/test_egress_client.py`. Here we exercise
the PostgREST-specific concerns: header construction, body shape,
status-code → `SubmitOutcome` mapping, and `EgressDenied` handling.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest
from llm_tracker_plugin_supabase_sink.client import (
    ExchangeRecord,
    SubmitOutcome,
    SupabaseSinkClient,
)
from llm_tracker_sdk.egress import EgressDenied, EgressResponse


class _StubEgress:
    """Minimal `EgressClient` stand-in. Records calls; replies as configured."""

    def __init__(
        self,
        responses: list[EgressResponse | EgressDenied] | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    async def fetch(
        self,
        url: str,
        *,
        method: str = "POST",
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> EgressResponse:
        self.calls.append(
            {
                "url": url,
                "method": method,
                "headers": dict(headers or {}),
                "body": body,
                "timeout": timeout,
            }
        )
        if not self._responses:
            return EgressResponse(status_code=201, headers={}, body=b"")
        nxt = self._responses.pop(0)
        if isinstance(nxt, EgressDenied):
            raise nxt
        return nxt


def _record(**overrides: Any) -> ExchangeRecord:
    base: dict[str, Any] = {
        "exchange_id": "x-1",
        "session_id": "s-1",
        "ts_started_ms": 1_700_000_000_000,
        "mode": "R",
        "endpoint": "v1/messages",
        "source": "supabase_sink/0.1.0",
        "model_requested": "claude-test",
        "model_served": "claude-test",
        "stop_reason": "end_turn",
        "input_tokens": 12,
        "output_tokens": 34,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "request_text": "[user]\nhi",
        "response_text": "Hello!",
        "raw_request": {"model": "claude-test", "messages": [{"role": "user", "content": "hi"}]},
        "raw_response": {"model": "claude-test", "stop_reason": "end_turn"},
    }
    base.update(overrides)
    return ExchangeRecord(**base)


def _headers_factory() -> Mapping[str, str]:
    # Simulates env-backed factory; real plugin closes over os.environ.
    return {"apikey": "fake-service-role", "Authorization": "Bearer fake-service-role"}


# -- happy / idempotent / retry / terminal mappings -------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (200, SubmitOutcome.OK),
        (201, SubmitOutcome.OK),
        (409, SubmitOutcome.IDEMPOTENT_SKIP),
        (500, SubmitOutcome.RETRY),
        (502, SubmitOutcome.RETRY),
        (503, SubmitOutcome.RETRY),
        (400, SubmitOutcome.TERMINAL_FAILURE),
        (401, SubmitOutcome.TERMINAL_FAILURE),
        (403, SubmitOutcome.TERMINAL_FAILURE),
        (404, SubmitOutcome.TERMINAL_FAILURE),
    ],
)
async def test_submit_status_code_mapping(status: int, expected: SubmitOutcome):
    egress = _StubEgress([EgressResponse(status_code=status, headers={}, body=b"")])
    client = SupabaseSinkClient(
        url="https://x.test/rest/v1/exchanges",
        headers_factory=_headers_factory,
        egress=egress,
    )
    outcome = await client.submit(_record())
    assert outcome is expected


async def test_submit_egress_denied_is_terminal_failure():
    egress = _StubEgress(
        [EgressDenied(url="https://x.test/rest/v1/exchanges", reason="denied_by_egress_guard")]
    )
    client = SupabaseSinkClient(
        url="https://x.test/rest/v1/exchanges",
        headers_factory=_headers_factory,
        egress=egress,
    )
    outcome = await client.submit(_record())
    assert outcome is SubmitOutcome.TERMINAL_FAILURE


# -- request shape ----------------------------------------------------------


async def test_submit_posts_to_configured_url_with_postgrest_headers():
    egress = _StubEgress([EgressResponse(status_code=201, headers={}, body=b"")])
    url = "https://qdcixbwwlsnkekabavmj.supabase.co/rest/v1/exchanges"
    client = SupabaseSinkClient(url=url, headers_factory=_headers_factory, egress=egress)

    await client.submit(_record())

    assert len(egress.calls) == 1
    call = egress.calls[0]
    assert call["url"] == url
    assert call["method"] == "POST"
    assert call["headers"]["apikey"] == "fake-service-role"
    assert call["headers"]["Authorization"] == "Bearer fake-service-role"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["headers"]["Prefer"] == "resolution=ignore-duplicates"


async def test_submit_body_is_json_array_of_one_row():
    egress = _StubEgress([EgressResponse(status_code=201, headers={}, body=b"")])
    client = SupabaseSinkClient(
        url="https://x.test/rest/v1/exchanges",
        headers_factory=_headers_factory,
        egress=egress,
    )
    rec = _record(exchange_id="x-42")

    await client.submit(rec)

    body_bytes = egress.calls[0]["body"]
    parsed = json.loads(body_bytes)
    assert isinstance(parsed, list) and len(parsed) == 1
    row = parsed[0]
    assert row["exchange_id"] == "x-42"
    assert row["mode"] == "R"
    assert row["source"] == "supabase_sink/0.1.0"
    # raw_request should round-trip as a nested object, not a JSON string.
    assert row["raw_request"] == {
        "model": "claude-test",
        "messages": [{"role": "user", "content": "hi"}],
    }


async def test_headers_factory_is_invoked_per_call_not_cached():
    """Pins the no-string-attribute promise: the key must be re-read
    each submit so a long-lived client never holds it as state.
    """
    counter = {"n": 0}

    def factory() -> Mapping[str, str]:
        counter["n"] += 1
        return {"apikey": f"key-{counter['n']}", "Authorization": f"Bearer key-{counter['n']}"}

    egress = _StubEgress(
        [
            EgressResponse(status_code=201, headers={}, body=b""),
            EgressResponse(status_code=201, headers={}, body=b""),
            EgressResponse(status_code=201, headers={}, body=b""),
        ]
    )
    client = SupabaseSinkClient(
        url="https://x.test/rest/v1/exchanges", headers_factory=factory, egress=egress
    )

    await client.submit(_record(exchange_id="a"))
    await client.submit(_record(exchange_id="b"))
    await client.submit(_record(exchange_id="c"))

    assert counter["n"] == 3
    assert egress.calls[0]["headers"]["apikey"] == "key-1"
    assert egress.calls[2]["headers"]["apikey"] == "key-3"


async def test_submit_handles_record_with_null_optional_fields():
    """Block / Abort exchanges may have empty parsed text and zero usage."""
    egress = _StubEgress([EgressResponse(status_code=201, headers={}, body=b"")])
    client = SupabaseSinkClient(
        url="https://x.test/rest/v1/exchanges",
        headers_factory=_headers_factory,
        egress=egress,
    )
    rec = _record(
        model_requested=None,
        model_served=None,
        stop_reason=None,
        input_tokens=None,
        output_tokens=None,
        cache_creation_input_tokens=None,
        cache_read_input_tokens=None,
        request_text=None,
        response_text=None,
        raw_request=None,
        raw_response=None,
    )

    outcome = await client.submit(rec)

    assert outcome is SubmitOutcome.OK
    body = json.loads(egress.calls[0]["body"])[0]
    assert body["model_requested"] is None
    assert body["request_text"] is None
    assert body["raw_request"] is None
