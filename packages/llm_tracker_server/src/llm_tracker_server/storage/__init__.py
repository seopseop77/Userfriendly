"""Storage layer: SQLAlchemy async engine + PostgreSQL models.

Schema is greenfield-server per Phase 3c plan: the four user-data tables
(`exchanges`, `events`, `tool_calls`, `audit_log`) are ported one-to-one
from the local-sidecar SQLite schema but typed against PostgreSQL. The two
tenancy substrate tables (`orgs`, `api_tokens`) land in CP3 and anchor
ADR-0018 / ADR-0020. CP4 (migration `0004_org_id_on_user_data`) adds the
`org_id` NOT NULL FK column to the four user-data tables. CP5
(migration `0005_rls_policies`) adds the RLS half of defense-in-depth
on those same tables -- per-org policy keyed off
`current_setting('app.org_id', true)` plus an admin policy branch
keyed off `app.role`. Per-request session binding (`SET LOCAL
app.org_id`) lands in CP6/CP9.
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
