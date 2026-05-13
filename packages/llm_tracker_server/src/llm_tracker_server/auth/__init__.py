"""Auth surface (ADR-0020 Axis 1, header per ADR-0023).

Axis 1 of ADR-0020: per-org bearer tokens. The agent presents
`X-LLM-Tracker-Token: <token>` (ADR-0023 — `Authorization` is reserved
for the Anthropic credential pass-through); the server hashes it
(SHA-256 hex), looks up `api_tokens`, resolves the org, and binds the
per-request DB session to the matching org for RLS (CP5).

Two halves:

- `tokens` -- pure helpers: `hash_token`, `lookup`, `issue`, `revoke`,
  `list_for_org`. No HTTP; the Typer CLI (`cli.main`) and the
  middleware both call these.
- `middleware` -- the FastAPI/Starlette HTTP middleware that wraps
  every authenticated route. Open one session per request, drop to
  `llm_tracker_app`, set `app.org_id`, hand the session to downstream
  handlers via `request.state.session`. CP9 will route storage
  INSERTs through the same session.

Axis 2 (Anthropic credential pass-through) lands in CP7.
"""

from llm_tracker_server.auth.middleware import AuthMiddleware
from llm_tracker_server.auth.tokens import (
    PLAINTEXT_PREFIX,
    generate_plaintext,
    hash_token,
    issue,
    list_for_org,
    lookup,
    revoke,
)

__all__ = [
    "PLAINTEXT_PREFIX",
    "AuthMiddleware",
    "generate_plaintext",
    "hash_token",
    "issue",
    "list_for_org",
    "lookup",
    "revoke",
]
