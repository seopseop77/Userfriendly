"""End-to-end ``on_persisted`` against real Postgres + pgvector (ADR-0030 CP5).

Skipped unless ``LLMTRACK_TEST_DATABASE_URL`` is set; uses the conftest
fixture's role-wrapped session factory so RLS on ``scope_chunks`` /
``scope_documents`` actually fires (the docker-default superuser would
bypass it).

What we pin here:

1. Stage-1 in / out routing writes the correct ``scope_alerts.stage`` +
   ``flagged`` columns + ``matched_chunk_id`` linking back to the chunk.
2. Stage-2 routing actually calls the judge and persists the verdict +
   reason on the same row.
3. The RLS-protected ``scope_chunks`` lookup is per-org: when org A and
   org B each have a chunk at the identical embedding, org A's
   evaluation matches the org-A chunk (not org-B's), and vice versa.
4. An org with zero chunks → no ``scope_alerts`` row (ADR-0030 §D9).

The OpenAI clients are swapped out for in-process stubs so the test
never touches the network; the pipeline math runs over real pgvector
cosine distance, not the stubbed similarity values from the pure-pipeline
unit tests.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
import sqlalchemy as sa
from llm_tracker_plugin_scope_guard.pipeline import Thresholds
from llm_tracker_plugin_scope_guard.plugin import ScopeGuard
from llm_tracker_plugin_scope_guard.storage import _vector_literal
from llm_tracker_sdk import HookContext

TEST_DB_URL = os.environ.get("LLMTRACK_TEST_DATABASE_URL", "")
SKIP_REASON = "LLMTRACK_TEST_DATABASE_URL not set; PG smoke test skipped"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)

_EMBED_DIM = 1536


# -----------------------------------------------------------------------------
# Stubs — replace the real OpenAI clients
# -----------------------------------------------------------------------------


class _StubEmbed:
    """Returns a pre-canned embedding per input string."""

    def __init__(self, by_input: dict[str, list[float]]) -> None:
        self._by_input = by_input
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return self._by_input[text]


class _StubJudge:
    """Returns a single canned verdict regardless of input."""

    def __init__(self, verdict: str = "in_scope", reason: str = "stub reason") -> None:
        self.verdict = verdict
        self.reason = reason
        self.calls: list[tuple[str, list[str]]] = []

    async def judge(self, message_text: str, chunks: list[str]) -> tuple[str, str]:
        self.calls.append((message_text, list(chunks)))
        return self.verdict, self.reason


# -----------------------------------------------------------------------------
# Vector helpers
# -----------------------------------------------------------------------------


def _unit_vector(position: int) -> list[float]:
    """1536-dim unit vector with the only non-zero at ``position``."""
    v = [0.0] * _EMBED_DIM
    v[position] = 1.0
    return v


def _two_axis_vector(p0: float, p1: float) -> list[float]:
    """1536-dim vector with mass only on dims 0 and 1.

    For a unit-vector chunk at position 0 the cosine similarity reduces to
    ``p0 / sqrt(p0² + p1²)`` — so ``(0.6, 0.8)`` gives a clean ``0.6``
    similarity for the ambiguous-band test.
    """
    v = [0.0] * _EMBED_DIM
    v[0] = p0
    v[1] = p1
    return v


# -----------------------------------------------------------------------------
# DB seeding helpers
# -----------------------------------------------------------------------------


async def _seed_org(session, name: str) -> uuid.UUID:
    """Insert a new ``orgs`` row (RLS-off) and return its id."""
    result = await session.execute(
        sa.text("INSERT INTO orgs (name) VALUES (:n) RETURNING id"),
        {"n": name},
    )
    org_id = result.scalar_one()
    await session.commit()
    return org_id


async def _seed_document_with_chunks(
    session,
    *,
    org_id: uuid.UUID,
    title: str,
    chunks: list[tuple[str, list[float]]],
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Insert one ``scope_documents`` row + N ``scope_chunks`` rows.

    Both tables are RLS-on so the caller must bind ``app.org_id`` first
    (handled in ``_seed_two_orgs``).
    """
    doc_id = uuid.uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO scope_documents (id, org_id, title, content) "
            "VALUES (:id, :org_id, :title, :content)"
        ),
        {"id": doc_id, "org_id": org_id, "title": title, "content": "seeded"},
    )
    chunk_ids: list[uuid.UUID] = []
    for idx, (content, vec) in enumerate(chunks):
        cid = uuid.uuid4()
        chunk_ids.append(cid)
        await session.execute(
            sa.text(
                "INSERT INTO scope_chunks "
                "(id, document_id, org_id, chunk_index, content, embedding) "
                "VALUES (:id, :doc_id, :org_id, :idx, :content, CAST(:vec AS vector))"
            ),
            {
                "id": cid,
                "doc_id": doc_id,
                "org_id": org_id,
                "idx": idx,
                "content": content,
                "vec": _vector_literal(vec),
            },
        )
    await session.commit()
    return doc_id, chunk_ids


# -----------------------------------------------------------------------------
# HookContext + plugin construction
# -----------------------------------------------------------------------------


def _ctx_with_message(org_id: uuid.UUID, message_text: str) -> HookContext:
    body = json.dumps({"messages": [{"role": "user", "content": message_text}]}).encode("utf-8")
    # ``user_opted_in=True`` lifts the L0 ceiling that mode R defaults to;
    # mirrors the analytics_sink test's ctx shape. The plugin's manifest
    # ``min_content_level="L3"`` would do the same via the host's ``_ceiling``
    # pin in production.
    ctx = HookContext(
        session_id="server",
        exchange_id="ex_test",
        mode="R",
        user_opted_in=True,
        _raw_request_body=body,
    )
    ctx.org_id = org_id
    return ctx


def _build_plugin(
    session_factory,
    embed: _StubEmbed,
    judge: _StubJudge,
    *,
    thresholds: Thresholds | None = None,
) -> ScopeGuard:
    plugin = ScopeGuard(
        session_factory=session_factory,
        embed_client=embed,
        judge_client=judge,
        thresholds=thresholds or Thresholds(),
        window=5,
    )
    return plugin


async def _fetch_alert(session_factory, exchange_id: str):
    async with session_factory() as session:
        result = await session.execute(
            sa.text(
                "SELECT exchange_id, org_id, stage, flagged, max_similarity, "
                "matched_chunk_id, stage2_verdict, stage2_reason "
                "FROM scope_alerts WHERE exchange_id = :ex"
            ),
            {"ex": exchange_id},
        )
        return result.one_or_none()


async def _count_alerts(session_factory) -> int:
    async with session_factory() as session:
        result = await session.execute(sa.text("SELECT COUNT(*) FROM scope_alerts"))
        return int(result.scalar_one())


# -----------------------------------------------------------------------------
# Shared per-test seeding
# -----------------------------------------------------------------------------


async def _seed_two_orgs_with_corpora(session_factory):
    """Seed orgs A and B, each with one chunk at the same axis-0 vector.

    Chunk content is distinct per org so the matched-chunk row identifies
    *which* org's corpus served the lookup — this is what the RLS check
    falls out of.
    """
    async with session_factory() as session:
        org_a = await _seed_org(session, "scope-org-a")
    async with session_factory() as session:
        org_b = await _seed_org(session, "scope-org-b")

    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('app.org_id', :v, true)"),
            {"v": str(org_a)},
        )
        _, a_chunks = await _seed_document_with_chunks(
            session,
            org_id=org_a,
            title="A scope",
            chunks=[("org A chunk content", _unit_vector(0))],
        )

    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('app.org_id', :v, true)"),
            {"v": str(org_b)},
        )
        _, b_chunks = await _seed_document_with_chunks(
            session,
            org_id=org_b,
            title="B scope",
            chunks=[("org B chunk content", _unit_vector(0))],
        )

    return {"a": (org_a, a_chunks[0]), "b": (org_b, b_chunks[0])}


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


async def test_high_similarity_writes_stage1_in_row(session_factory) -> None:
    """Similarity 1.0 against the org's chunk → stage1_in, flagged=False."""
    orgs = await _seed_two_orgs_with_corpora(session_factory)
    org_a, chunk_a = orgs["a"]

    embed = _StubEmbed({"in scope question": _unit_vector(0)})
    judge = _StubJudge(verdict="in_scope", reason="should not run")
    plugin = _build_plugin(session_factory, embed, judge)

    ctx = _ctx_with_message(org_a, "in scope question")
    await plugin.on_persisted("ex_high", ctx)

    row = await _fetch_alert(session_factory, "ex_high")
    assert row is not None
    assert row.org_id == org_a
    assert row.stage == "stage1_in"
    assert row.flagged is False
    assert row.max_similarity == pytest.approx(1.0, abs=1e-6)
    assert row.matched_chunk_id == chunk_a
    assert row.stage2_verdict is None
    assert row.stage2_reason is None
    # Judge was not called.
    assert judge.calls == []


async def test_low_similarity_writes_stage1_out_row(session_factory) -> None:
    """Similarity 0.0 against the org's chunk → stage1_out, flagged=True."""
    orgs = await _seed_two_orgs_with_corpora(session_factory)
    org_a, chunk_a = orgs["a"]

    # Message embeds on dim 2 — orthogonal to the seeded chunk at dim 0.
    embed = _StubEmbed({"unrelated question": _unit_vector(2)})
    judge = _StubJudge(verdict="in_scope", reason="should not run")
    plugin = _build_plugin(session_factory, embed, judge)

    ctx = _ctx_with_message(org_a, "unrelated question")
    await plugin.on_persisted("ex_low", ctx)

    row = await _fetch_alert(session_factory, "ex_low")
    assert row is not None
    assert row.stage == "stage1_out"
    assert row.flagged is True
    assert row.max_similarity == pytest.approx(0.0, abs=1e-6)
    assert row.matched_chunk_id == chunk_a  # nearest chunk even though distance is high
    assert row.stage2_verdict is None
    assert judge.calls == []


async def test_ambiguous_similarity_invokes_judge_and_writes_stage2(session_factory) -> None:
    """Similarity in band → judge runs; verdict + reason persist on the row."""
    orgs = await _seed_two_orgs_with_corpora(session_factory)
    org_a, chunk_a = orgs["a"]

    # cosine([1,0,...], [0.6,0.8,0,...]) = 0.6 — falls inside the default
    # ambiguous band (threshold 0.6 ± 0.05).
    embed = _StubEmbed({"borderline question": _two_axis_vector(0.6, 0.8)})
    judge = _StubJudge(verdict="out_of_scope", reason="judge said no")
    plugin = _build_plugin(session_factory, embed, judge)

    ctx = _ctx_with_message(org_a, "borderline question")
    await plugin.on_persisted("ex_ambig", ctx)

    row = await _fetch_alert(session_factory, "ex_ambig")
    assert row is not None
    assert row.stage == "stage2_out"
    assert row.flagged is True
    assert row.max_similarity == pytest.approx(0.6, abs=1e-6)
    assert row.matched_chunk_id == chunk_a
    assert row.stage2_verdict == "out_of_scope"
    assert row.stage2_reason == "judge said no"
    # Judge was called once with the message + the top-K chunk content.
    assert len(judge.calls) == 1
    msg, chunks = judge.calls[0]
    assert msg == "borderline question"
    assert chunks == ["org A chunk content"]


async def test_rls_isolates_per_org_max_cosine_lookup(session_factory) -> None:
    """Org A's evaluation matches org A's chunk; org B's matches org B's.

    Both orgs have a chunk at the *identical* embedding — only RLS can
    decide which one shows up in the result set. The matched_chunk_id
    column persists that decision for the operator to attribute later.
    """
    orgs = await _seed_two_orgs_with_corpora(session_factory)
    org_a, chunk_a = orgs["a"]
    org_b, chunk_b = orgs["b"]

    embed = _StubEmbed({"same question": _unit_vector(0)})
    judge = _StubJudge()
    plugin = _build_plugin(session_factory, embed, judge)

    # Org A's exchange first.
    ctx_a = _ctx_with_message(org_a, "same question")
    ctx_a.exchange_id = "ex_org_a"
    await plugin.on_persisted("ex_org_a", ctx_a)

    # Org B's exchange against the same plugin instance + same message text.
    ctx_b = _ctx_with_message(org_b, "same question")
    ctx_b.exchange_id = "ex_org_b"
    await plugin.on_persisted("ex_org_b", ctx_b)

    row_a = await _fetch_alert(session_factory, "ex_org_a")
    row_b = await _fetch_alert(session_factory, "ex_org_b")
    assert row_a is not None and row_a.org_id == org_a
    assert row_a.matched_chunk_id == chunk_a  # not chunk_b — RLS isolation
    assert row_b is not None and row_b.org_id == org_b
    assert row_b.matched_chunk_id == chunk_b


async def test_org_without_corpus_writes_no_alert(session_factory) -> None:
    """ADR-0030 §D9 — org with zero ``scope_chunks`` → silent no-op."""
    # Seed only org A's corpus; create org C with no chunks at all.
    await _seed_two_orgs_with_corpora(session_factory)
    async with session_factory() as session:
        org_c = await _seed_org(session, "scope-org-c-empty")

    embed = _StubEmbed({"any question": _unit_vector(0)})
    judge = _StubJudge()
    plugin = _build_plugin(session_factory, embed, judge)

    ctx = _ctx_with_message(org_c, "any question")
    await plugin.on_persisted("ex_no_corpus", ctx)

    assert await _fetch_alert(session_factory, "ex_no_corpus") is None
    # And the embed was attempted (we don't pre-check corpus size).
    assert embed.calls == ["any question"]
