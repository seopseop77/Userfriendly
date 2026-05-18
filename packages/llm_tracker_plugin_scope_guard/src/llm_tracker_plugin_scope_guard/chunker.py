"""Semantic boundary detection for scope_documents (ADR-0030 §D5).

Stub for CP2. CP3 implements:

- Sentence segmentation (MVP regex; ``blingfire`` / ``pysbd`` deferred
  per ADR-0030 §Deferred §6).
- Per-sentence embedding (uses :mod:`.embeddings`).
- Walk adjacent cosine similarities, insert a chunk boundary where the
  similarity drops below the rolling-mean baseline (algorithm + window
  size pinned at CP3 — ADR-0030 §Q1).
- Enforce min 50 / max 500 token bounds.
"""

from __future__ import annotations
