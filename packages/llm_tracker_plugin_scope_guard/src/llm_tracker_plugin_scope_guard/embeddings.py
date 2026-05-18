"""OpenAI ``text-embedding-3-small`` client (ADR-0030 §D3).

Egress flows through :class:`llm_tracker_sdk.egress.EgressClient` (ADR-0015) to
``https://api.openai.com/v1/embeddings``. Vector dim 1536, token limit 8191.

The class accepts the API key and ``EgressClient`` by constructor injection so
unit tests can substitute a stub client without touching the network.
``plugin.py`` constructs the real instance from ``self.egress`` +
``OPENAI_API_KEY`` at ``on_init`` time in CP5.
"""

from __future__ import annotations

import json

from llm_tracker_sdk.egress import EgressClient, EgressResponse

_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
_MODEL = "text-embedding-3-small"
_EXPECTED_DIM = 1536


class EmbeddingError(RuntimeError):
    """Raised when the embeddings endpoint returns an unexpected payload.

    The plugin's ``on_persisted`` path catches this and logs + continues; an
    embedding failure must never crash the host (ADR-0030 §D1 — observe-only).
    """


class EmbeddingClient:
    """Thin wrapper over :class:`EgressClient` for ``text-embedding-3-small``."""

    def __init__(self, *, api_key: str, egress: EgressClient, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._egress = egress
        self._timeout = timeout

    async def embed(self, text: str) -> list[float]:
        """Return the 1536-dim embedding for ``text``.

        Raises :class:`EmbeddingError` on non-2xx response or on a payload that
        does not match OpenAI's documented shape
        (``{"data": [{"embedding": [...]}]}``). :class:`EgressDenied` from the
        guard is allowed to propagate so callers see the denial in-band.
        """
        body = json.dumps({"model": _MODEL, "input": text}).encode("utf-8")
        resp: EgressResponse = await self._egress.fetch(
            _EMBEDDINGS_URL,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            body=body,
            timeout=self._timeout,
        )
        if resp.status_code < 200 or resp.status_code >= 300:
            raise EmbeddingError(
                f"openai embeddings returned status {resp.status_code}: {resp.body[:200]!r}"
            )
        try:
            payload = json.loads(resp.body)
            vector = payload["data"][0]["embedding"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise EmbeddingError(f"unexpected embeddings payload shape: {exc}") from exc
        if not isinstance(vector, list) or len(vector) != _EXPECTED_DIM:
            actual_dim = len(vector) if isinstance(vector, list) else "n/a"
            raise EmbeddingError(f"unexpected embedding vector: dim={actual_dim}")
        return [float(v) for v in vector]
