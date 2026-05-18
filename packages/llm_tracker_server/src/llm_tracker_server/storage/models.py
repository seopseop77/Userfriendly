"""SQLAlchemy ORM models for the central server (PostgreSQL).

User-data tables: `exchanges`, `audit_log`.
Tenancy substrate: `orgs`, `api_tokens`.

Migration 0013 dropped `events` and `tool_calls` (never had INSERT call
sites) and removed token count columns from `exchanges`
(input_tokens, output_tokens, cache_read_tokens, cache_write_tokens).
Token counts are stored in `plugin_analytics` by the analytics_sink plugin,
which is the authoritative source for per-exchange cost data.

Dialect notes vs. SQLite-era schema:
- Epoch-millisecond / counter columns use `BigInteger` (PG BIGINT) to avoid
  INT4 overflow in 2038.
- Primary keys remain `String` (ULIDs generated at the application layer).
- `audit_log` append-only enforcement uses a PL/pgSQL trigger shipped by
  migration `0002_audit_log_triggers`.

CP4 adds `org_id UUID NOT NULL REFERENCES orgs(id)` on user-data tables
(ADR-0018). No SA relationship declared — RLS (CP5) is the authority for
cross-org visibility. Per-request session binding lands in CP6.
"""

import uuid as uuid_module
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Exchange(Base):
    __tablename__ = "exchanges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[uuid_module.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ended_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    model_requested: Mapped[str | None] = mapped_column(String, nullable=True)
    model_served: Mapped[str | None] = mapped_column(String, nullable=True)
    status_code: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    t_request_received_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    t_upstream_first_byte_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    t_client_first_byte_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_level: Mapped[str] = mapped_column(String, nullable=False)
    blocked_by: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (Index("idx_exchanges_started", "started_at"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[uuid_module.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id"),
        nullable=False,
    )
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


class Org(Base):
    """Tenancy root (ADR-0018). One row per organisation."""

    __tablename__ = "orgs"

    id: Mapped[uuid_module.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )


class ApiToken(Base):
    """Per-org bearer token (ADR-0020). Stored as SHA-256 hex of plaintext."""

    __tablename__ = "api_tokens"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    org_id: Mapped[uuid_module.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
