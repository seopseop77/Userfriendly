"""SQLAlchemy ORM models for the llm-tracker core tables."""

from sqlalchemy import DDL, ForeignKey, Index, Integer, String, Text, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Exchange(Base):
    __tablename__ = "exchanges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[int] = mapped_column(Integer, nullable=False)
    ended_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    model_requested: Mapped[str | None] = mapped_column(String, nullable=True)
    model_served: Mapped[str | None] = mapped_column(String, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    t_request_received_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    t_upstream_first_byte_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    t_client_first_byte_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    content_level: Mapped[str] = mapped_column(String, nullable=False)
    blocked_by: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (Index("idx_exchanges_started", "started_at"),)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    exchange_id: Mapped[str] = mapped_column(String, ForeignKey("exchanges.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[int] = mapped_column(Integer, nullable=False)
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
    # Append-only. DB-level enforcement via SQLite triggers below
    # (mirrors the Alembic migration so test fixtures using
    # Base.metadata.create_all also get the triggers; see ADR-0006).
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    ts: Mapped[int] = mapped_column(Integer, nullable=False)
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


# audit_log append-only triggers (ADR-0006). The SQL below is the source
# of truth; the Alembic migration that ships these triggers in production
# DBs executes the same statements.

AUDIT_LOG_NO_UPDATE_DDL = (
    "CREATE TRIGGER IF NOT EXISTS audit_log_no_update "
    "BEFORE UPDATE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"
)

AUDIT_LOG_NO_DELETE_DDL = (
    "CREATE TRIGGER IF NOT EXISTS audit_log_no_delete "
    "BEFORE DELETE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"
)

event.listen(AuditLog.__table__, "after_create", DDL(AUDIT_LOG_NO_UPDATE_DDL))
event.listen(AuditLog.__table__, "after_create", DDL(AUDIT_LOG_NO_DELETE_DDL))
