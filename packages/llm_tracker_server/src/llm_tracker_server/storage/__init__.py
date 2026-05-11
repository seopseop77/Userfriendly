"""Storage layer: SQLAlchemy async engine + PostgreSQL models.

Schema is greenfield-server per Phase 3c plan: the four user-data tables
(`exchanges`, `events`, `tool_calls`, `audit_log`) are ported one-to-one
from the local-sidecar SQLite schema but typed against PostgreSQL. The two
tenancy substrate tables (`orgs`, `api_tokens`) land in CP3 and anchor
ADR-0018 / ADR-0020. The `org_id` column on the user-data tables lands in
CP4; RLS policies in CP5; per-request session binding in CP6/CP9.
"""

from llm_tracker_server.storage.engine import make_engine, make_session_factory
from llm_tracker_server.storage.models import (
    ApiToken,
    AuditLog,
    Base,
    Event,
    Exchange,
    Org,
    ToolCall,
)

__all__ = [
    "ApiToken",
    "AuditLog",
    "Base",
    "Event",
    "Exchange",
    "Org",
    "ToolCall",
    "make_engine",
    "make_session_factory",
]
