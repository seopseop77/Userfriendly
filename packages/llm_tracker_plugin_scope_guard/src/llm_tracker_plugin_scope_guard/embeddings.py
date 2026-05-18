"""OpenAI ``text-embedding-3-small`` client (ADR-0030 §D3).

Stub for CP2. CP4 implements the ``EmbeddingClient`` that flows through
:class:`llm_tracker_server.egress_guard.client.HostEgressClient` (ADR-0015)
to ``https://api.openai.com/v1/embeddings``. Vector dim 1536, token
limit 8191.
"""

from __future__ import annotations
