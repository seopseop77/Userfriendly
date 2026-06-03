"""Process-wide settings for the signup app (pydantic-settings, env prefix LLMTRACK_).

`database_url` points at the same Supabase PostgreSQL that
`llm_tracker_server` writes to — the signup app shares the
``orgs`` / ``api_tokens`` / ``participant_registrations`` tables but
runs as a separate Fly service.

`proxy_server_url` is the public URL of the proxy server. The signup
app shows it on the success page so participants can configure the
local agent (``claude-manage setup …``) to point at the right
backend.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = ""
    proxy_server_url: str = ""
    # Cloudflare Turnstile (anti-bot). Verification is enforced only when
    # `turnstile_secret` is set; with both empty the form behaves as before.
    turnstile_site_key: str = ""
    turnstile_secret: str = ""

    model_config = {"env_prefix": "LLMTRACK_"}
