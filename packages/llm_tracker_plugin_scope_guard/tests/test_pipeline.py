"""Pipeline unit tests — pure-function stage routing (ADR-0030 §D2).

These tests exercise :func:`pipeline.evaluate` against three trivial stubs
(``embed``, ``judge``, ``max_cosine_lookup``) so the routing arithmetic
stands on its own — no database, no HTTP, no plugin glue.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import pytest
from llm_tracker_plugin_scope_guard.pipeline import (
    ChunkCandidate,
    ScopeEvaluation,
    Thresholds,
    evaluate,
)


def _candidate(similarity: float, content: str = "chunk text") -> ChunkCandidate:
    return ChunkCandidate(id=uuid.uuid4(), content=content, similarity=similarity)


def _stub_embed(vec: list[float]):
    async def _f(_text: str) -> list[float]:
        return vec

    return _f


def _stub_judge(verdict: str, reason: str, calls: list | None = None):
    async def _f(text: str, chunks: list[str]):
        if calls is not None:
            calls.append((text, list(chunks)))
        return verdict, reason

    return _f


def _stub_lookup(candidates: Sequence[ChunkCandidate]):
    async def _f(_vec: list[float], _k: int):
        return candidates

    return _f


_DEFAULT_THRESHOLDS = Thresholds()  # threshold=0.6, band=0.1, judge_top_k=3


@pytest.mark.asyncio
async def test_empty_corpus_returns_none() -> None:
    """Org with zero ``scope_chunks`` → no evaluation, no alert written."""
    result = await evaluate(
        "msg",
        embed=_stub_embed([0.1, 0.2]),
        judge=_stub_judge("in_scope", "stub"),
        max_cosine_lookup=_stub_lookup([]),
        thresholds=_DEFAULT_THRESHOLDS,
    )
    assert result is None


@pytest.mark.asyncio
async def test_high_similarity_routes_stage1_in() -> None:
    """similarity >= threshold + band/2 → stage1_in, flagged=False, no judge."""
    judge_calls: list = []
    top = _candidate(0.70)  # 0.70 >= 0.6 + 0.05
    result = await evaluate(
        "msg",
        embed=_stub_embed([0.1]),
        judge=_stub_judge("out_of_scope", "should not run", calls=judge_calls),
        max_cosine_lookup=_stub_lookup([top]),
        thresholds=_DEFAULT_THRESHOLDS,
    )
    assert result == ScopeEvaluation(
        stage="stage1_in",
        flagged=False,
        max_similarity=0.70,
        matched_chunk_id=top.id,
        stage2_verdict=None,
        stage2_reason=None,
    )
    assert judge_calls == []


@pytest.mark.asyncio
async def test_low_similarity_routes_stage1_out() -> None:
    """similarity <= threshold - band/2 → stage1_out, flagged=True, no judge."""
    judge_calls: list = []
    top = _candidate(0.40)  # 0.40 <= 0.6 - 0.05
    result = await evaluate(
        "msg",
        embed=_stub_embed([0.1]),
        judge=_stub_judge("in_scope", "should not run", calls=judge_calls),
        max_cosine_lookup=_stub_lookup([top]),
        thresholds=_DEFAULT_THRESHOLDS,
    )
    assert result == ScopeEvaluation(
        stage="stage1_out",
        flagged=True,
        max_similarity=0.40,
        matched_chunk_id=top.id,
        stage2_verdict=None,
        stage2_reason=None,
    )
    assert judge_calls == []


@pytest.mark.asyncio
async def test_band_edges_with_clean_thresholds() -> None:
    """Use ``threshold=0.5, band=0.2`` (binary-float-clean) to pin band edges.

    With the default 0.6 / 0.1 the lower bound computes as 0.5499999... in
    IEEE-754, so a similarity literally equal to 0.55 lands inside the band
    and routes to Stage 2 — that is operator-visible behaviour, not a bug,
    but it makes for a fragile test. The 0.5 / 0.2 pair gives 0.4 and 0.6
    exactly, so the boundary check pins the inequality direction (``>=`` /
    ``<=``) without surprises.
    """
    clean = Thresholds(threshold=0.5, band=0.2, judge_top_k=3)
    upper = await evaluate(
        "msg",
        embed=_stub_embed([0.1]),
        judge=_stub_judge("out_of_scope", "ignored"),
        max_cosine_lookup=_stub_lookup([_candidate(0.60)]),
        thresholds=clean,
    )
    lower = await evaluate(
        "msg",
        embed=_stub_embed([0.1]),
        judge=_stub_judge("in_scope", "ignored"),
        max_cosine_lookup=_stub_lookup([_candidate(0.40)]),
        thresholds=clean,
    )
    assert upper is not None and upper.stage == "stage1_in"
    assert lower is not None and lower.stage == "stage1_out"


@pytest.mark.asyncio
async def test_ambiguous_routes_to_stage2_in() -> None:
    """In-band similarity + judge says in_scope → stage2_in, flagged=False."""
    judge_calls: list = []
    candidates = [_candidate(0.60, "c1"), _candidate(0.58, "c2"), _candidate(0.56, "c3")]
    result = await evaluate(
        "msg text",
        embed=_stub_embed([0.1]),
        judge=_stub_judge("in_scope", "matches chunk 1", calls=judge_calls),
        max_cosine_lookup=_stub_lookup(candidates),
        thresholds=_DEFAULT_THRESHOLDS,
    )
    assert result is not None
    assert result.stage == "stage2_in"
    assert result.flagged is False
    assert result.max_similarity == 0.60
    assert result.matched_chunk_id == candidates[0].id
    assert result.stage2_verdict == "in_scope"
    assert result.stage2_reason == "matches chunk 1"
    # Judge receives the message + the top-K chunk contents in order.
    assert judge_calls == [("msg text", ["c1", "c2", "c3"])]


@pytest.mark.asyncio
async def test_ambiguous_routes_to_stage2_out() -> None:
    """In-band similarity + judge says out_of_scope → stage2_out, flagged=True."""
    candidates = [_candidate(0.60, "c1")]
    result = await evaluate(
        "msg text",
        embed=_stub_embed([0.1]),
        judge=_stub_judge("out_of_scope", "unrelated"),
        max_cosine_lookup=_stub_lookup(candidates),
        thresholds=_DEFAULT_THRESHOLDS,
    )
    assert result is not None
    assert result.stage == "stage2_out"
    assert result.flagged is True
    assert result.stage2_verdict == "out_of_scope"
    assert result.stage2_reason == "unrelated"


@pytest.mark.asyncio
async def test_lookup_receives_judge_top_k_from_thresholds() -> None:
    """The ``judge_top_k`` knob flows through to the lookup call's ``k``."""
    seen_k: list[int] = []

    async def _lookup(_vec: list[float], k: int):
        seen_k.append(k)
        return [_candidate(0.99)]

    await evaluate(
        "msg",
        embed=_stub_embed([0.1]),
        judge=_stub_judge("in_scope", "ignored"),
        max_cosine_lookup=_lookup,
        thresholds=Thresholds(threshold=0.6, band=0.1, judge_top_k=7),
    )
    assert seen_k == [7]
