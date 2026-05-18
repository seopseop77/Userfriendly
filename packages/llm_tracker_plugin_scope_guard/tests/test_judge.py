"""Unit tests for ``llm_tracker_plugin_scope_guard.judge``.

Pins the Stage-2 prompt template (ADR-0030 §Q4) and the malformed-JSON
fallback behaviour. The :class:`EgressClient` is stubbed so tests do not
touch the network.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest
from llm_tracker_plugin_scope_guard.judge import (
    _DEFAULT_VERDICT,
    _MALFORMED_REASON,
    _SYSTEM_PROMPT,
    JudgeClient,
    JudgeError,
)
from llm_tracker_sdk.egress import EgressDenied, EgressResponse


class _StubEgress:
    def __init__(self, response: EgressResponse | Exception) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

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
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _chat_response(verdict: str = "out_of_scope", reason: str = "off topic") -> EgressResponse:
    content = json.dumps({"verdict": verdict, "reason": reason})
    payload = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "model": "gpt-4o-mini",
    }
    return EgressResponse(
        status_code=200,
        headers={"content-type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
    )


def _raw_chat_response(raw_content: str) -> EgressResponse:
    payload = {"choices": [{"message": {"role": "assistant", "content": raw_content}}]}
    return EgressResponse(
        status_code=200,
        headers={"content-type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
    )


def test_q4_prompt_template_is_frozen():
    """ADR-0030 §Q4 pins the system prompt's exact wording. Future tweaks must
    bump the test (and become diff-visible in review)."""
    sentinels = [
        "scope-monitoring judge",
        "strict JSON only",
        '"verdict": "in_scope" | "out_of_scope"',
        '"reason":',
        "in_scope when",
        "out_of_scope when",
    ]
    for s in sentinels:
        assert s in _SYSTEM_PROMPT, f"missing sentinel: {s!r}"


def test_default_verdict_matches_db_literal():
    """``scope_alerts.verdict`` accepts ``in_scope`` / ``out_of_scope`` only."""
    assert _DEFAULT_VERDICT in ("in_scope", "out_of_scope")


@pytest.mark.asyncio
async def test_judge_returns_verdict_and_reason_on_success():
    egress = _StubEgress(_chat_response("out_of_scope", "user asked about cooking"))
    client = JudgeClient(api_key="sk", egress=egress)
    verdict, reason = await client.judge("how do I bake bread", ["chunk A about taxes"])
    assert verdict == "out_of_scope"
    assert reason == "user asked about cooking"


@pytest.mark.asyncio
async def test_judge_request_pins_url_model_and_message_shape():
    egress = _StubEgress(_chat_response())
    client = JudgeClient(api_key="sk-test-99", egress=egress)
    await client.judge("user msg", ["chunk one", "chunk two"])

    assert len(egress.calls) == 1
    call = egress.calls[0]
    assert call["url"] == "https://api.openai.com/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-test-99"
    body = json.loads(call["body"])
    assert body["model"] == "gpt-4o-mini"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.0
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][0]["content"] == _SYSTEM_PROMPT
    user_content = body["messages"][1]["content"]
    assert "user msg" in user_content
    assert "1. chunk one" in user_content
    assert "2. chunk two" in user_content


@pytest.mark.asyncio
async def test_judge_handles_empty_chunks():
    """If retrieval returns no chunks (empty corpus or short doc), still issue
    the call — the model should default the verdict given no scope evidence."""
    egress = _StubEgress(_chat_response("out_of_scope", "no scope evidence"))
    client = JudgeClient(api_key="sk", egress=egress)
    verdict, _ = await client.judge("anything", [])
    body = json.loads(egress.calls[0]["body"])
    assert "(no scope chunks supplied)" in body["messages"][1]["content"]
    assert verdict == "out_of_scope"


@pytest.mark.asyncio
async def test_judge_tolerates_whitespace_around_content_json():
    """OpenAI's JSON mode is reliable but tests pin the trim path explicitly so
    a leading/trailing newline never re-routes to the fallback."""
    egress = _StubEgress(
        _raw_chat_response('\n  {"verdict": "in_scope", "reason": "matches chunk 1"}  \n')
    )
    client = JudgeClient(api_key="sk", egress=egress)
    verdict, reason = await client.judge("m", ["c"])
    assert verdict == "in_scope"
    assert reason == "matches chunk 1"


@pytest.mark.asyncio
async def test_judge_falls_back_on_invalid_json_content():
    """Malformed model output → ``(_DEFAULT_VERDICT, _MALFORMED_REASON)``.

    The fallback is per ADR-0030 §D1 (observe-only) — better to record an
    alert with a degraded verdict than to crash ``on_persisted``.
    """
    egress = _StubEgress(_raw_chat_response("definitely not json"))
    client = JudgeClient(api_key="sk", egress=egress)
    verdict, reason = await client.judge("m", ["c"])
    assert verdict == _DEFAULT_VERDICT
    assert reason == _MALFORMED_REASON


@pytest.mark.asyncio
async def test_judge_falls_back_on_unexpected_verdict_value():
    """Out-of-vocab verdict (e.g. ``"maybe"``) → fallback, not pass-through.

    Storing an unexpected literal would break operator dashboards that filter
    on the two known values.
    """
    egress = _StubEgress(_raw_chat_response('{"verdict": "maybe", "reason": "hmm"}'))
    client = JudgeClient(api_key="sk", egress=egress)
    verdict, reason = await client.judge("m", ["c"])
    assert verdict == _DEFAULT_VERDICT
    assert reason == _MALFORMED_REASON


@pytest.mark.asyncio
async def test_judge_falls_back_on_missing_choices_field():
    """Body shape that doesn't match OpenAI's documented response → fallback,
    not raise. The transport returned 2xx so the audit log already booked a
    successful egress; surfacing as a crash would mis-attribute the failure."""
    egress = _StubEgress(EgressResponse(status_code=200, headers={}, body=b'{"oops": true}'))
    client = JudgeClient(api_key="sk", egress=egress)
    verdict, reason = await client.judge("m", ["c"])
    assert verdict == _DEFAULT_VERDICT
    assert reason == _MALFORMED_REASON


@pytest.mark.asyncio
async def test_judge_raises_on_non_2xx():
    egress = _StubEgress(EgressResponse(status_code=500, headers={}, body=b"server error"))
    client = JudgeClient(api_key="sk", egress=egress)
    with pytest.raises(JudgeError) as exc_info:
        await client.judge("m", ["c"])
    assert "500" in str(exc_info.value)


@pytest.mark.asyncio
async def test_judge_propagates_egress_denied():
    egress = _StubEgress(EgressDenied(url="x", reason="denied_by_egress_guard"))
    client = JudgeClient(api_key="sk", egress=egress)
    with pytest.raises(EgressDenied):
        await client.judge("m", ["c"])
