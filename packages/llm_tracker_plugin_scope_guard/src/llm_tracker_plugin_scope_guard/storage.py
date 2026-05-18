"""Persistence — ``scope_chunks`` reads and ``scope_alerts`` writes (ADR-0030 §D7/§D8).

Both helpers take an ``async_sessionmaker``-shaped ``session_factory`` rather
than a raw :class:`AsyncEngine` so the plugin can hand the test fixture's
role-wrapped factory in unchanged (``conftest.py`` issues
``SET LOCAL ROLE llm_tracker_app`` per session, mirroring the production
non-superuser DB role). The production wiring in :mod:`.plugin` builds a
plain ``async_sessionmaker`` over its own engine — the Supabase connection
string already supplies the app role.

The pgvector bind shape uses ``CAST(:vec AS vector)`` against a string
literal we render here (``[v1,v2,...]``) instead of importing the
``pgvector.sqlalchemy`` adapter. The literal path is dependency-light,
matches the migration's column type exactly, and avoids registering a
codec on the asyncpg connection — the SELECTs only return ``float``
values, never the raw vector.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from .pipeline import ChunkCandidate


class SessionFactory(Protocol):
    """The shape both ``async_sessionmaker`` and the conftest wrapper expose."""

    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]: ...


# Cosine distance via pgvector's ``<=>`` operator; ``1 - distance`` is the
# similarity scalar the pipeline thresholds against (ADR-0030 §D7).
_SELECT_TOP_CHUNKS_SQL = sa.text(
    """
    SELECT id,
           content,
           1 - (embedding <=> CAST(:vec AS vector)) AS similarity
      FROM scope_chunks
     WHERE org_id = :org_id
     ORDER BY embedding <=> CAST(:vec AS vector) ASC
     LIMIT :k
    """
)


_INSERT_ALERT_SQL = sa.text(
    """
    INSERT INTO scope_alerts (
        id, exchange_id, org_id, stage, flagged, max_similarity,
        matched_chunk_id, stage2_verdict, stage2_reason
    ) VALUES (
        :id, :exchange_id, :org_id, :stage, :flagged, :max_similarity,
        :matched_chunk_id, :stage2_verdict, :stage2_reason
    )
    """
)


def _vector_literal(vec: Sequence[float]) -> str:
    """Render ``vec`` as a pgvector text literal: ``[v1,v2,...]``.

    ``.18g`` gives lossless float → string round-trip without scientific
    notation surprises that ``repr()`` can introduce on edge values.
    """
    return "[" + ",".join(format(float(v), ".18g") for v in vec) + "]"


async def select_top_chunks_by_cosine(
    session_factory: SessionFactory,
    *,
    org_id: uuid.UUID,
    vector: Sequence[float],
    k: int,
) -> list[ChunkCandidate]:
    """Return the org's top-``k`` most-similar chunks by cosine distance.

    Issues ``SET LOCAL app.org_id`` before the SELECT so the per-row RLS
    policy on ``scope_chunks`` (migration 0010) admits the read. The bound
    org_id also appears in the WHERE clause so the filter is explicit at
    the query layer even when the session role bypasses RLS (e.g. a local
    superuser dev DB).
    """
    vec_lit = _vector_literal(vector)
    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('app.org_id', :v, true)"),
            {"v": str(org_id)},
        )
        result = await session.execute(
            _SELECT_TOP_CHUNKS_SQL,
            {"vec": vec_lit, "org_id": org_id, "k": k},
        )
        rows = result.all()
    return [
        ChunkCandidate(id=row.id, content=row.content, similarity=float(row.similarity))
        for row in rows
    ]


async def insert_alert(
    session_factory: SessionFactory,
    *,
    exchange_id: str,
    org_id: uuid.UUID,
    stage: str,
    flagged: bool,
    max_similarity: float,
    matched_chunk_id: uuid.UUID | None,
    stage2_verdict: str | None,
    stage2_reason: str | None,
) -> None:
    """Insert one row into ``scope_alerts`` (no RLS — migration 0010 §D8).

    Uses a ULID-derived UUID for the primary key so the rows order by
    insertion time when sorted by ``id`` alone, parallel to how
    ``analytics_sink`` stamps ``plugin_analytics.id``.
    """
    async with session_factory() as session:
        await session.execute(
            _INSERT_ALERT_SQL,
            {
                "id": ULID().to_uuid(),
                "exchange_id": exchange_id,
                "org_id": org_id,
                "stage": stage,
                "flagged": flagged,
                "max_similarity": max_similarity,
                "matched_chunk_id": matched_chunk_id,
                "stage2_verdict": stage2_verdict,
                "stage2_reason": stage2_reason,
            },
        )
        await session.commit()
