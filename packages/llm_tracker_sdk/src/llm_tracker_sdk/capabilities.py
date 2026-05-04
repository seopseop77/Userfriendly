"""Capability token vocabulary (design.md §6.3.3).

Plugins declare required capabilities in plugin.toml. The operator approves
each capability at install time; a manifest change triggers re-approval.
"""

# Data access — read-only
READ_REQUEST_METADATA = "read_request_metadata"
"""Model name, token counts, scrubbed headers, timing."""

READ_REQUEST_CONTENT = "read_request_content"
"""User prompts and tool_result bodies."""

READ_RESPONSE_METADATA = "read_response_metadata"
"""Response usage, stop_reason."""

READ_RESPONSE_CONTENT = "read_response_content"
"""Response body (including streamed chunks)."""

# Intervention
MODIFY_REQUEST = "modify_request"
"""Mutate the upstream request before forward (before_forward hook)."""

BLOCK_REQUEST = "block_request"
"""Issue a synthetic block response."""

ABORT_RESPONSE = "abort_response"
"""Terminate an in-progress response stream."""

# Storage
READ_PERSISTED_DATA = "read_persisted_data"
"""Read the local SQLite DB."""

WRITE_PLUGIN_TABLES = "write_plugin_tables"
"""Write to the plugin's own namespace in the DB."""

# Egress
EGRESS_HTTP = "egress_http"
"""Outbound HTTP through EgressGuard (allowlist required)."""

ALL_CAPABILITIES: frozenset[str] = frozenset(
    {
        READ_REQUEST_METADATA,
        READ_REQUEST_CONTENT,
        READ_RESPONSE_METADATA,
        READ_RESPONSE_CONTENT,
        MODIFY_REQUEST,
        BLOCK_REQUEST,
        ABORT_RESPONSE,
        READ_PERSISTED_DATA,
        WRITE_PLUGIN_TABLES,
        EGRESS_HTTP,
    }
)
