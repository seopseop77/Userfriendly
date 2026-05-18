"""Unit tests for ``llm_tracker_plugin_scope_guard.embeddings``.

The :class:`EgressClient` is stubbed so tests never reach the network. The
stub captures the request shape so we can pin the model / URL / auth header
contract against ADR-0031 §D1.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest
from llm_tracker_plugin_scope_guard.embeddings import (
    EmbeddingClient,
    EmbeddingError,
)
from llm_tracker_sdk.egress import EgressDenied, EgressResponse


class _StubEgress:
    """Records the last call; returns a configurable response."""

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


def _ok_embedding(dim: int = 768) -> EgressResponse:
    payload = {"embedding": {"values": [0.0] * dim}}
    return EgressResponse(
        status_code=200,
        headers={"content-type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
    )


@pytest.mark.asyncio
async def test_embed_returns_vector_of_expected_dim():
    egress = _StubEgress(_ok_embedding())
    client = EmbeddingClient(api_key="sk-test", egress=egress)
    vec = await client.embed("hello world")
    assert len(vec) == 768
    assert all(isinstance(v, float) for v in vec)


@pytest.mark.asyncio
async def test_embed_request_pins_url_model_and_auth():
    """ADR-0031 §D1: target the Gemini embedContent endpoint, the exact model,
    and carry the API key as ``x-goog-api-key``."""
    egress = _StubEgress(_ok_embedding())
    client = EmbeddingClient(api_key="gemini-test-42", egress=egress)
    await client.embed("input text")

    assert len(egress.calls) == 1
    call = egress.calls[0]
    assert call["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent"
    )
    assert call["method"] == "POST"
    assert call["headers"]["x-goog-api-key"] == "gemini-test-42"
    assert call["headers"]["Content-Type"] == "application/json"
    body = json.loads(call["body"])
    assert body == {
        "model": "models/text-embedding-004",
        "content": {"parts": [{"text": "input text"}]},
    }


@pytest.mark.asyncio
async def test_embed_propagates_egress_denied():
    """The guard's denial is allowed through so the plugin can log + skip
    rather than masking it as a transport error."""
    egress = _StubEgress(EgressDenied(url="x", reason="denied_by_egress_guard"))
    client = EmbeddingClient(api_key="sk", egress=egress)
    with pytest.raises(EgressDenied):
        await client.embed("ignored")


@pytest.mark.asyncio
async def test_embed_raises_on_non_2xx():
    egress = _StubEgress(EgressResponse(status_code=429, headers={}, body=b"rate limited"))
    client = EmbeddingClient(api_key="sk", egress=egress)
    with pytest.raises(EmbeddingError) as exc_info:
        await client.embed("anything")
    assert "429" in str(exc_info.value)


@pytest.mark.asyncio
async def test_embed_raises_on_malformed_payload():
    egress = _StubEgress(
        EgressResponse(status_code=200, headers={}, body=b'{"error": "no embedding field"}')
    )
    client = EmbeddingClient(api_key="sk", egress=egress)
    with pytest.raises(EmbeddingError):
        await client.embed("anything")


@pytest.mark.asyncio
async def test_embed_raises_on_wrong_dim():
    """A short or long vector means the model / API changed; fail loudly so
    storage doesn't accept a malformed row."""
    egress = _StubEgress(_ok_embedding(dim=512))
    client = EmbeddingClient(api_key="sk", egress=egress)
    with pytest.raises(EmbeddingError):
        await client.embed("anything")


@pytest.mark.asyncio
async def test_embed_passes_timeout():
    egress = _StubEgress(_ok_embedding())
    client = EmbeddingClient(api_key="sk", egress=egress, timeout=12.5)
    await client.embed("text")
    assert egress.calls[0]["timeout"] == 12.5
