"""Storage layer: SQLAlchemy async engine + PostgreSQL models + INSERT helpers.

Migration 0013 dropped `events` and `tool_calls` tables and token count
columns from `exchanges`. The two tenancy substrate tables (`orgs`,
`api_tokens`) land in CP3 (ADR-0018 / ADR-0020). CP4 adds `org_id` to
user-data tables; CP5 adds RLS; CP6 wires per-request session binding.
CP9 routes INSERTs through the request-scoped session so RLS applies to
writes and `org_id` is set explicitly on every row (defense in depth).
"""

from llm_tracker_server.storage.audit import write_audit
from llm_tracker_server.storage.engine import make_engine, make_session_factory
from llm_tracker_server.storage.exchanges import (
    record_exchange_blocked,
    record_exchange_failure,
    record_exchange_timing,
)
from llm_tracker_server.storage.models import (
    ApiToken,
    AuditLog,
    Base,
    Exchange,
    Org,
)

__all__ = [
    "ApiToken",
    "AuditLog",
    "Base",
    "Exchange",
    "Org",
    "make_engine",
    "make_session_factory",
    "record_exchange_blocked",
    "record_exchange_failure",
    "record_exchange_timing",
    "write_audit",
]
