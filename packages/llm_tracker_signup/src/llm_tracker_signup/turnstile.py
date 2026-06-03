"""Cloudflare Turnstile server-side verification for the signup form.

The widget on the registration form produces a one-time token in the
``cf-turnstile-response`` field; this module exchanges that token (plus
the site secret) at Cloudflare's siteverify endpoint to confirm the
submission came from a human rather than a bot.

Verification is **fail-closed**: any missing token, network error, or
non-success response yields ``False``. That couples signup availability
to Cloudflare, which is acceptable because Cloudflare already fronts the
whole site (the tunnel) — if Cloudflare is down, the form is unreachable
anyway. Enforcement happens only when a secret is configured; see
``app.register_submit``.
"""

from __future__ import annotations

import httpx

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile(secret: str, token: str, remote_ip: str | None) -> bool:
    """Return True iff Cloudflare confirms the Turnstile token is valid."""
    if not token:
        return False
    data = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(SITEVERIFY_URL, data=data)
    except httpx.HTTPError:
        return False
    if resp.status_code != 200:
        return False
    return bool(resp.json().get("success", False))
