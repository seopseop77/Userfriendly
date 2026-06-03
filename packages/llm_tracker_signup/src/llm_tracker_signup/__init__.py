"""Public-facing signup app for research participants.

A FastAPI service that serves a registration form, accepts a participant's
contact details (name, email, institution), issues an API token for the
proxy server, and shows the token on-screen exactly once. The proxy
server URL is never exposed here; the participant only ever sees this app.

Token issuance is duplicated from `llm_tracker_server.auth.tokens` as raw
async SQL so this package depends only on the public PostgreSQL schema,
not on the proxy-server package. See `docs/worklog/2026-05-21-signup-app.md`
for the rationale.
"""

__version__ = "0.0.1"
