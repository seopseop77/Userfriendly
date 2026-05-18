"""Two-stage decision logic (ADR-0030 §D2).

Pure async function: take the message text plus three injected callables
(``embed``, ``judge``, ``max_cosine_lookup``) and return a
:class:`ScopeEvaluation` ready for :func:`.storage.insert_alert`. No
SQLAlchemy or HTTP imports here so unit tests can drive the routing
deterministically with simple stubs.

Stage routing per ADR-0030 §D2::

    similarity >= threshold + band/2 → "stage1_in"  (flagged=False)
    similarity <= threshold - band/2 → "stage1_out" (flagged=True; no Stage 2)
    otherwise                        → Stage 2 judge call
                                       → "stage2_in"  (flagged=False)
                                       → "stage2_out" (flagged=True)

A row is always written for every evaluation (matches the §D8 docstring
"one row per ``on_persisted`` evaluation" and the partial index
``WHERE flagged`` that splits the hot from the cold rows for operator
review). When the org has zero chunks the function returns ``None`` —
the plugin treats that as "no corpus, no alert" per ADR-0030 §D9.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["in_scope", "out_of_scope"]


@dataclass(frozen=True)
class ChunkCandidate:
    """One row of the max-cosine lookup over ``scope_chunks``."""

    id: uuid.UUID
    content: str
    similarity: float


@dataclass(frozen=True)
class Thresholds:
    """ADR-0030 §D9 operator-tunable knobs."""

    threshold: float = 0.6
    band: float = 0.1
    judge_top_k: int = 3


@dataclass(frozen=True)
class ScopeEvaluation:
    """Terminal verdict for one ``on_persisted`` evaluation.

    Maps 1 : 1 to a ``scope_alerts`` row (minus the plugin-stamped
    ``id`` / ``exchange_id`` / ``org_id`` / ``created_at``).
    """

    stage: str  # stage1_in | stage1_out | stage2_in | stage2_out
    flagged: bool
    max_similarity: float
    matched_chunk_id: uuid.UUID | None
    stage2_verdict: Verdict | None
    stage2_reason: str | None


EmbedFn = Callable[[str], Awaitable[list[float]]]
JudgeFn = Callable[[str, list[str]], Awaitable[tuple[Verdict, str]]]
LookupFn = Callable[[list[float], int], Awaitable[Sequence[ChunkCandidate]]]


async def evaluate(
    message_text: str,
    *,
    embed: EmbedFn,
    judge: JudgeFn,
    max_cosine_lookup: LookupFn,
    thresholds: Thresholds,
) -> ScopeEvaluation | None:
    """Run the two-stage pipeline. Returns ``None`` when the corpus is empty."""
    vector = await embed(message_text)
    candidates = await max_cosine_lookup(vector, thresholds.judge_top_k)
    if not candidates:
        return None

    top = candidates[0]
    half_band = thresholds.band / 2.0
    if top.similarity >= thresholds.threshold + half_band:
        return ScopeEvaluation(
            stage="stage1_in",
            flagged=False,
            max_similarity=top.similarity,
            matched_chunk_id=top.id,
            stage2_verdict=None,
            stage2_reason=None,
        )
    if top.similarity <= thresholds.threshold - half_band:
        return ScopeEvaluation(
            stage="stage1_out",
            flagged=True,
            max_similarity=top.similarity,
            matched_chunk_id=top.id,
            stage2_verdict=None,
            stage2_reason=None,
        )

    verdict, reason = await judge(message_text, [c.content for c in candidates])
    suffix = "out" if verdict == "out_of_scope" else "in"
    return ScopeEvaluation(
        stage=f"stage2_{suffix}",
        flagged=(verdict == "out_of_scope"),
        max_similarity=top.similarity,
        matched_chunk_id=top.id,
        stage2_verdict=verdict,
        stage2_reason=reason,
    )
