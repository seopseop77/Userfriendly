"""SQLAlchemy ORM models for the central server (PostgreSQL).

Ported one-to-one from `packages/llm_tracker/src/llm_tracker/storage/models.py`
with three deliberate dialect adjustments:

- Timestamp / counter columns that hold epoch-millisecond or large counts
  are `BigInteger` (PG `BIGINT`) instead of `Integer` (PG `INT4`). The
  SQLite source used `Integer` because SQLite's INTEGER is variable-width;
  PG's `INT4` would overflow epoch-ms in 2038.
- Primary keys remain `String` (ULIDs generated at the application layer).
  Switching to `BIGINT IDENTITY` or `UUID DEFAULT gen_random_uuid()` would
  break the existing ULID-producing call sites in Phase 1/2 code without
  buying anything CP2 needs. The Phase 3c plan's mention of identity/UUID
  defaults applies to the new tenancy tables (`orgs`, `api_tokens`) that
  land in CP3.
- `audit_log` append-only enforcement uses a PL/pgSQL trigger function
  shipped by migration `0002_audit_log_triggers`. SQLite's per-table
  `RAISE(ABORT)` triggers don't port; the SQL is in the migration file,
  not duplicated here.

`org_id` and RLS land in CP4/CP5 — not in this checkpoint.
"""

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Exchange(Base):
    __tablename__ = "exchanges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ended_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    model_requested: Mapped[str | None] = mapped_column(String, nullable=True)
    model_served: Mapped[str | None] = mapped_column(String, nullable=True)
    status_code: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    t_request_received_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    t_upstream_first_byte_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    t_client_first_byte_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tool_call_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    content_level: Mapped[str] = mapped_column(String, nullable=False)
    blocked_by: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (Index("idx_exchanges_started", "started_at"),)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    exchange_id: Mapped[str] = mapped_column(String, ForeignKey("exchanges.id"), nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ts: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("idx_events_exchange", "exchange_id", "seq"),)


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    exchange_id: Mapped[str] = mapped_column(String, ForeignKey("exchanges.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    ts: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    plugin: Mapped[str | None] = mapped_column(String, nullable=True)
    hook: Mapped[str | None] = mapped_column(String, nullable=True)
    capability: Mapped[str | None] = mapped_column(String, nullable=True)
    destination: Mapped[str | None] = mapped_column(String, nullable=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_audit_ts", "ts"),
        Index("idx_audit_plugin", "plugin"),
    )
