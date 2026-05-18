"""Tests for the operator CLI (``process_scope_document``, ADR-0030 §D5).

Three contract surfaces:

1. **Argument validation** — bad UUIDs, missing files, and unsupported
   suffixes exit cleanly via ``SystemExit`` so the operator gets a
   useful message instead of a Python traceback.
2. **Idempotent re-registration (DB-fixture)** — registering the same
   ``(org_id, title)`` twice ends up with exactly one
   ``scope_documents`` row and a chunk count matching round 2 only;
   round 1's chunks are cascaded away by the migration-0010
   ``ON DELETE CASCADE`` on ``scope_chunks.document_id``.
3. **Row shape (DB-fixture)** — the inserted ``scope_chunks`` rows
   carry the right ``org_id`` + ``document_id`` and a contiguous
   ``chunk_index`` starting at 0.
"""

from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from llm_tracker_plugin_scope_guard.process_scope_document import (
    _validate_args,
    register_document,
)

TEST_DB_URL = os.environ.get("LLMTRACK_TEST_DATABASE_URL", "")
SKIP_REASON = "LLMTRACK_TEST_DATABASE_URL not set; PG smoke test skipped"

_EMBED_DIM = 768


# -----------------------------------------------------------------------------
# Argument validation — no DB needed
# -----------------------------------------------------------------------------


def _make_args(*, org_id: str, file: Path, title: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(org_id=org_id, file=file, title=title)


def test_validate_rejects_non_uuid_org_id(tmp_path: Path) -> None:
    file = tmp_path / "scope.txt"
    file.write_text("anything")
    with pytest.raises(SystemExit, match="invalid org_id"):
        _validate_args(_make_args(org_id="not-a-uuid", file=file))


def test_validate_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.txt"
    with pytest.raises(SystemExit, match="file not found"):
        _validate_args(_make_args(org_id=str(uuid.uuid4()), file=missing))


def test_validate_rejects_unsupported_suffix(tmp_path: Path) -> None:
    file = tmp_path / "scope.pdf"
    file.write_text("anything")
    with pytest.raises(SystemExit, match="unsupported file type"):
        _validate_args(_make_args(org_id=str(uuid.uuid4()), file=file))


def test_validate_accepts_txt_and_returns_stem_as_default_title(tmp_path: Path) -> None:
    file = tmp_path / "company-scope.txt"
    file.write_text("scope content")
    org_id, file_path, title = _validate_args(_make_args(org_id=str(uuid.uuid4()), file=file))
    assert isinstance(org_id, uuid.UUID)
    assert file_path == file
    assert title == "company-scope"


def test_validate_explicit_title_wins_over_stem(tmp_path: Path) -> None:
    file = tmp_path / "scope.md"
    file.write_text("scope content")
    _, _, title = _validate_args(
        _make_args(org_id=str(uuid.uuid4()), file=file, title="Custom Title")
    )
    assert title == "Custom Title"


def test_validate_accepts_md_files(tmp_path: Path) -> None:
    file = tmp_path / "scope.md"
    file.write_text("scope content")
    _, file_path, _ = _validate_args(_make_args(org_id=str(uuid.uuid4()), file=file))
    assert file_path.suffix == ".md"


# -----------------------------------------------------------------------------
# DB-fixture idempotency — runs against pgvector/pgvector:pg15
# -----------------------------------------------------------------------------

pytestmark_db = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)


class _UnitEmbed:
    """Returns a constant unit vector — deterministic, dim-correct, content-agnostic.

    The idempotency contract doesn't depend on similarity math, so a
    constant vector is enough. The chunker still runs its boundary
    detection (all sims = 1.0 → no boundaries fire) and size enforcement
    (single chunk under the 500-word ceiling → kept as-is).
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        v = [0.0] * _EMBED_DIM
        v[0] = 1.0
        return v


async def _seed_org(session, name: str) -> uuid.UUID:
    result = await session.execute(
        sa.text("INSERT INTO orgs (name) VALUES (:n) RETURNING id"),
        {"n": name},
    )
    org_id = result.scalar_one()
    await session.commit()
    return org_id


async def _counts_for(session_factory, org_id: uuid.UUID, title: str) -> tuple[int, int]:
    """Return (scope_documents count, scope_chunks count) for the (org_id, title)."""
    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('app.org_id', :v, true)"),
            {"v": str(org_id)},
        )
        docs = await session.scalar(
            sa.text("SELECT COUNT(*) FROM scope_documents WHERE org_id = :o AND title = :t"),
            {"o": org_id, "t": title},
        )
        chunks = await session.scalar(
            sa.text(
                "SELECT COUNT(*) FROM scope_chunks "
                "WHERE document_id IN ("
                "  SELECT id FROM scope_documents WHERE org_id = :o AND title = :t"
                ")"
            ),
            {"o": org_id, "t": title},
        )
        return int(docs or 0), int(chunks or 0)


@pytestmark_db
async def test_register_then_reregister_replaces_chunks(session_factory) -> None:
    """Re-registering the same (org_id, title) keeps exactly one doc + the latest chunks.

    ADR-0030 §D5 mandates idempotent delete-then-insert; the
    migration-0010 ``ON DELETE CASCADE`` does the chunk cleanup.
    """
    async with session_factory() as session:
        org_id = await _seed_org(session, "cli-org-idempotent")

    embed = _UnitEmbed()
    title = "scope.md"
    text_v1 = "First topic. Some more first-topic content."
    text_v2 = "Completely different. Brand new corpus content."

    doc_id_1, chunks_1 = await register_document(
        session_factory, embed, org_id=org_id, title=title, text=text_v1
    )
    docs_count_1, db_chunks_1 = await _counts_for(session_factory, org_id, title)
    assert docs_count_1 == 1
    assert db_chunks_1 == chunks_1
    assert chunks_1 >= 1

    doc_id_2, chunks_2 = await register_document(
        session_factory, embed, org_id=org_id, title=title, text=text_v2
    )
    docs_count_2, db_chunks_2 = await _counts_for(session_factory, org_id, title)
    # Idempotent: still one doc, not two.
    assert docs_count_2 == 1
    # Chunk count matches round 2 only — round 1's chunks were cascaded away.
    assert db_chunks_2 == chunks_2
    # Document id was regenerated (delete-then-insert, not update).
    assert doc_id_2 != doc_id_1


@pytestmark_db
async def test_register_writes_rows_with_sequential_chunk_index(
    session_factory,
) -> None:
    """Inserted chunks carry the right org_id + document_id + 0..N-1 chunk_index."""
    async with session_factory() as session:
        org_id = await _seed_org(session, "cli-org-shape")

    embed = _UnitEmbed()
    text = "Para one content. Para two content. Para three content."
    doc_id, chunks = await register_document(
        session_factory, embed, org_id=org_id, title="shape", text=text
    )

    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('app.org_id', :v, true)"),
            {"v": str(org_id)},
        )
        result = await session.execute(
            sa.text(
                "SELECT chunk_index, org_id, document_id "
                "FROM scope_chunks WHERE document_id = :d "
                "ORDER BY chunk_index ASC"
            ),
            {"d": doc_id},
        )
        rows = result.all()

    assert len(rows) == chunks
    for i, row in enumerate(rows):
        assert row.chunk_index == i
        assert row.org_id == org_id
        assert row.document_id == doc_id


@pytestmark_db
async def test_register_isolates_titles_within_same_org(session_factory) -> None:
    """Two titles under the same org → two scope_documents rows, not idempotent collapse."""
    async with session_factory() as session:
        org_id = await _seed_org(session, "cli-org-two-titles")

    embed = _UnitEmbed()
    await register_document(session_factory, embed, org_id=org_id, title="alpha", text="alpha text")
    await register_document(session_factory, embed, org_id=org_id, title="beta", text="beta text")

    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('app.org_id', :v, true)"),
            {"v": str(org_id)},
        )
        count = await session.scalar(
            sa.text("SELECT COUNT(*) FROM scope_documents WHERE org_id = :o"),
            {"o": org_id},
        )
    assert int(count) == 2
