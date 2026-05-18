"""Gemini ``text-embedding-004`` client (ADR-0031 §D1).

Egress flows through :class:`llm_tracker_sdk.egress.EgressClient`
(ADR-0015) to
``https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent``.
Vector dim 768.

The class accepts the API key and ``EgressClient`` by constructor
injection so unit tests can substitute a stub client without touching
the network. ``plugin.py`` constructs the real instance from
``self.egress`` + ``GEMINI_API_KEY`` at ``on_init`` time.

Supersedes the OpenAI ``text-embedding-3-small`` client picked in
ADR-0030 §D3.
"""

from __future__ import annotations

import json

from llm_tracker_sdk.egress import EgressClient, EgressResponse

_MODEL = "text-embedding-004"
_EMBEDDINGS_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL}:embedContent"
_EXPECTED_DIM = 768


class EmbeddingError(RuntimeError):
    """Raised when the embeddings endpoint returns an unexpected payload.

    The plugin's ``on_persisted`` path catches this and logs + continues; an
    embedding failure must never crash the host (ADR-0030 §D1 — observe-only).
    """


class EmbeddingClient:
    """Thin wrapper over :class:`EgressClient` for ``text-embedding-004``."""

    def __init__(self, *, api_key: str, egress: EgressClient, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._egress = egress
        self._timeout = timeout

    async def embed(self, text: str) -> list[float]:
        """Return the 768-dim embedding for ``text``.

        Raises :class:`EmbeddingError` on non-2xx response or on a payload that
        does not match Gemini's documented shape for a single
        ``embedContent`` call (``{"embedding": {"values": [...]}}``).
        :class:`EgressDenied` from the guard is allowed to propagate so
        callers see the denial in-band.
        """
        body = json.dumps(
            {
                "model": f"models/{_MODEL}",
                "content": {"parts": [{"text": text}]},
            }
        ).encode("utf-8")
        resp: EgressResponse = await self._egress.fetch(
            _EMBEDDINGS_URL,
            method="POST",
            headers={
                "x-goog-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            body=body,
            timeout=self._timeout,
        )
        if resp.status_code < 200 or resp.status_code >= 300:
            raise EmbeddingError(
                f"gemini embeddings returned status {resp.status_code}: {resp.body[:200]!r}"
            )
        try:
            payload = json.loads(resp.body)
            vector = payload["embedding"]["values"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise EmbeddingError(f"unexpected embeddings payload shape: {exc}") from exc
        if not isinstance(vector, list) or len(vector) != _EXPECTED_DIM:
            actual_dim = len(vector) if isinstance(vector, list) else "n/a"
            raise EmbeddingError(f"unexpected embedding vector: dim={actual_dim}")
        return [float(v) for v in vector]
