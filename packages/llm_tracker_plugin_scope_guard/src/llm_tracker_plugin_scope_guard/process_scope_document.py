"""Operator CLI for scope-document registration (ADR-0030 §D5 + §D9;
provider rev ADR-0031).

Reads a ``.txt`` or ``.md`` file, chunks it via the same algorithm
``ScopeGuard.on_persisted`` uses on the live corpus (ADR-0030 §D5),
embeds each chunk with Gemini ``text-embedding-004`` through a
standalone egress client (``_ToolEgressClient`` — no host, no audit
log; appropriate because the operator runs this script locally and
the only destination is Gemini's embeddings endpoint), and writes one
``scope_documents`` row + N ``scope_chunks`` rows under the given
``org_id``.

Idempotent re-registration: re-running the same ``(org_id, title)``
deletes any existing ``scope_documents`` row first (the migration-0010
``ON DELETE CASCADE`` on ``scope_chunks.document_id`` drops the
associated chunk rows), then inserts the fresh content. No versioning
— ADR-0030 §D5 picked delete-then-insert over versioning for MVP.

Invocations (both work after ``uv sync``)::

    process-scope-document <org_id> <file> [--title TITLE]
    python -m llm_tracker_plugin_scope_guard.process_scope_document ...

Required env: ``GEMINI_API_KEY`` and ``LLMTRACK_DATABASE_URL``. The CLI
refuses to start when either is unset (exit 2), mirroring the plugin's
``on_init`` fail-closed posture.

ADR-0030's "Implementation surface" section suggested
``tools/process_scope_document.py`` as one of two paths. We picked the
in-package module instead: it gives both a ``python -m`` entry-point
and a console-script (registered in ``pyproject.toml``), keeps the
testable code in the same package as its DB-fixture test, and avoids
spinning up a top-level ``tools/`` directory for a single script.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path

import httpx
import numpy as np
import sqlalchemy as sa
import structlog
from llm_tracker_sdk.egress import EgressClient, EgressResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from ulid import ULID

from .chunker import (
    ChunkRecord,
    _cosine,
    _detect_boundaries,
    _enforce_size_bounds,
    _group_into_chunks,
    _segment_sentences,
)
from .embeddings import EmbeddingClient
from .storage import _vector_literal

_SUPPORTED_SUFFIXES = (".txt", ".md")
_GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
_DATABASE_URL_ENV = "LLMTRACK_DATABASE_URL"


class _EmbedProtocol:
    """Structural type the CLI needs from :class:`EmbeddingClient` (for tests)."""

    async def embed(self, text: str) -> list[float]: ...  # pragma: no cover


class _ToolEgressClient(EgressClient):
    """Standalone :class:`EgressClient` adapter for operator tooling.

    The plugin's ``HostEgressClient`` wraps ``EgressGuard`` so audit +
    capability checks fire on every fetch. This script runs out-of-host
    (no ``PluginHost``, no audit log), so it just forwards to httpx.
    Safe because operators run this script locally and the only egress
    destination is Gemini's embeddings endpoint — the same allowlisted
    destination the plugin uses (ADR-0031 §D5).
    """

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client

    async def fetch(
        self,
        url: str,
        *,
        method: str = "POST",
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> EgressResponse:
        resp = await self._http.request(
            method,
            url,
            headers=dict(headers or {}),
            content=body,
            timeout=timeout,
        )
        return EgressResponse(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            body=resp.content,
        )


async def _chunk_document_async(text: str, embed_client: _EmbedProtocol) -> list[ChunkRecord]:
    """Async port of :func:`chunker.chunk_document` for the registration CLI.

    Reuses the chunker's pure helpers (sentence segmenter, boundary
    detection, group building, size enforcement) but ``await``s the
    Gemini embedding call instead of expecting a sync callable.
    Sequential is acceptable for a one-shot operator script — the
    chunker needs sentence vectors before computing similarities, so
    batching mid-pipeline would re-engineer the algorithm. The CLI
    pays N+M embedding round-trips for N sentences and M final chunks.
    """
    sentences = _segment_sentences(text)
    if not sentences:
        return []
    if len(sentences) == 1:
        vec = await embed_client.embed(sentences[0])
        return [ChunkRecord(0, sentences[0], vec)]

    sent_vecs = [np.asarray(await embed_client.embed(s), dtype=float) for s in sentences]
    similarities = [_cosine(sent_vecs[i], sent_vecs[i + 1]) for i in range(len(sentences) - 1)]
    boundaries = _detect_boundaries(similarities)
    groups = _group_into_chunks(len(sentences), boundaries)
    groups = _enforce_size_bounds(groups, sentences, similarities)

    records: list[ChunkRecord] = []
    for idx, group in enumerate(groups):
        content = " ".join(sentences[s] for s in group)
        vec = await embed_client.embed(content)
        records.append(ChunkRecord(idx, content, vec))
    return records


async def register_document(
    session_factory,
    embed_client: _EmbedProtocol,
    *,
    org_id: uuid.UUID,
    title: str,
    text: str,
) -> tuple[uuid.UUID, int]:
    """Idempotent delete-then-insert for ``(org_id, title)`` per ADR-0030 §D5.

    Returns ``(document_id, chunk_count)``. The document_id is freshly
    generated on every call — re-registration drops the prior row and
    inserts a new one, so the operator's "what's the canonical doc id
    for this title" answer comes from the most recent run.
    """
    records = await _chunk_document_async(text, embed_client)

    async with session_factory() as session:
        # Bind app.org_id so the RLS policies on scope_documents +
        # scope_chunks (migration 0010 _org_isolation) admit our delete
        # + insert calls.
        await session.execute(
            sa.text("SELECT set_config('app.org_id', :v, true)"),
            {"v": str(org_id)},
        )
        # Delete any prior (org_id, title) doc; the migration-0010
        # FK ON DELETE CASCADE on scope_chunks.document_id drops the
        # associated chunk rows in the same statement.
        await session.execute(
            sa.text("DELETE FROM scope_documents WHERE org_id = :org_id AND title = :title"),
            {"org_id": org_id, "title": title},
        )
        doc_id = ULID().to_uuid()
        await session.execute(
            sa.text(
                "INSERT INTO scope_documents (id, org_id, title, content) "
                "VALUES (:id, :org_id, :title, :content)"
            ),
            {"id": doc_id, "org_id": org_id, "title": title, "content": text},
        )
        for record in records:
            await session.execute(
                sa.text(
                    "INSERT INTO scope_chunks "
                    "(id, document_id, org_id, chunk_index, content, embedding) "
                    "VALUES (:id, :doc_id, :org_id, :idx, :content, "
                    "CAST(:vec AS vector))"
                ),
                {
                    "id": ULID().to_uuid(),
                    "doc_id": doc_id,
                    "org_id": org_id,
                    "idx": record.chunk_index,
                    "content": record.content,
                    "vec": _vector_literal(record.embedding),
                },
            )
        await session.commit()
    return doc_id, len(records)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="process-scope-document",
        description="Register a scope document for the given org (ADR-0030 §D5).",
    )
    parser.add_argument("org_id", help="UUID of the org owning this scope document.")
    parser.add_argument(
        "file",
        type=Path,
        help="Path to a .txt or .md file containing the scope corpus.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help=(
            "Document title (defaults to the file's stem). Used as the "
            "(org_id, title) idempotency key."
        ),
    )
    return parser.parse_args(argv)


def _validate_args(args: argparse.Namespace) -> tuple[uuid.UUID, Path, str]:
    """Validate parsed args and return ``(org_id, file_path, title)``.

    Raises :class:`SystemExit` with exit code 2 on any failure so the
    CLI surface matches the env-missing path.
    """
    try:
        org_id = uuid.UUID(args.org_id)
    except ValueError as exc:
        raise SystemExit(f"invalid org_id (must be a UUID): {exc}") from exc
    file_path: Path = args.file
    if not file_path.exists():
        raise SystemExit(f"file not found: {file_path}")
    if file_path.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise SystemExit(
            f"unsupported file type {file_path.suffix!r}; only "
            f"{', '.join(_SUPPORTED_SUFFIXES)} are accepted "
            "(ADR-0030 §D5 — PDFs/DOCX queued under §Deferred §3)"
        )
    title = args.title or file_path.stem
    return org_id, file_path, title


async def _amain(argv: list[str] | None = None) -> int:
    log = structlog.get_logger("process_scope_document")
    args = _parse_args(argv)
    org_id, file_path, title = _validate_args(args)

    api_key = os.environ.get(_GEMINI_API_KEY_ENV)
    if not api_key:
        print(f"{_GEMINI_API_KEY_ENV} is not set", file=sys.stderr)
        return 2
    db_url = os.environ.get(_DATABASE_URL_ENV)
    if not db_url:
        print(f"{_DATABASE_URL_ENV} is not set", file=sys.stderr)
        return 2

    text = file_path.read_text(encoding="utf-8")

    engine = create_async_engine(db_url, connect_args={"statement_cache_size": 0})
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with httpx.AsyncClient() as http_client:
            embed_client = EmbeddingClient(
                api_key=api_key,
                egress=_ToolEgressClient(http_client),
            )
            doc_id, chunk_count = await register_document(
                session_factory,
                embed_client,
                org_id=org_id,
                title=title,
                text=text,
            )
    finally:
        await engine.dispose()

    log.info(
        "scope_document.registered",
        org_id=str(org_id),
        title=title,
        document_id=str(doc_id),
        chunks=chunk_count,
    )
    print(f"document_id={doc_id}")
    print(f"title={title}")
    print(f"chunks={chunk_count}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(argv))


if __name__ == "__main__":
    raise SystemExit(main())
