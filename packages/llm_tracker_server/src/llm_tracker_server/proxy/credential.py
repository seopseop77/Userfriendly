"""Anthropic credential pass-through helpers (ADR-0020 Axis 2).

The server forwards whichever Anthropic-credential header Claude Code
natively sends. The canonical name is ``x-api-key`` (API-key users);
``anthropic-api-key`` is Anthropic's documented alternate; OAuth users
ride on ``Authorization: Bearer <oauth-token>``. All three are passed
through unchanged to ``api.anthropic.com``.

The *llm-tracker* per-org token rides on ``X-LLM-Tracker-Token``
(ADR-0023) and is consumed by ``AuthMiddleware`` before forwarding.
The forwarder strips it from outbound headers via
``proxy.forwarder._LOCAL_ONLY``; this module only enumerates the
Anthropic-credential-header set and the redaction primitives the
logging pipeline relies on.

The credential must never appear in any persisted artefact: no DB
column, no log line, no audit row. ``scrub_credential_processor`` is
the structlog defense-in-depth that redacts the credential bytes from
any log event regardless of which call site emitted them.
"""

from __future__ import annotations

from typing import Any

# Inbound credential header names the proxy passes through to Anthropic.
# Stored lowercase because Starlette normalises header keys to lowercase
# on access, and the lookup is case-insensitive in HTTP.
CREDENTIAL_HEADER_NAMES: frozenset[str] = frozenset(
    {
        "x-api-key",
        "anthropic-api-key",
    }
)

# Anthropic API-key plaintext prefix. The scrubber redacts any string
# value that begins with this prefix even when it appears inside a
# nested log field whose key is not a credential header (e.g. a stringy
# header dump or a copy-paste into an exception message).
ANTHROPIC_SECRET_PREFIX = "sk-ant-"

REDACTED = "[REDACTED]"


def is_credential_header(name: str) -> bool:
    """Case-insensitive check against the credential-header set."""
    return name.lower() in CREDENTIAL_HEADER_NAMES


def _scrub_value(value: Any) -> Any:
    """Recursively redact credentials in a single value."""
    if isinstance(value, dict):
        return _scrub_dict(value)
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_value(item) for item in value)
    if isinstance(value, str) and value.startswith(ANTHROPIC_SECRET_PREFIX):
        return REDACTED
    return value


def _scrub_dict(node: dict[Any, Any]) -> dict[Any, Any]:
    out: dict[Any, Any] = {}
    for key, value in node.items():
        if isinstance(key, str) and is_credential_header(key):
            out[key] = REDACTED
        else:
            out[key] = _scrub_value(value)
    return out


def scrub_credential_processor(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor: redact Anthropic credentials in any event.

    Runs late in the chain (just before the renderer) so it sees the
    fully-merged event dict. Two redaction rules:

    1. Any key whose name is in :data:`CREDENTIAL_HEADER_NAMES` has its
       value replaced with :data:`REDACTED`, regardless of nesting depth.
    2. Any string value beginning with :data:`ANTHROPIC_SECRET_PREFIX`
       is replaced with :data:`REDACTED`, regardless of where it
       appears. Defends against accidental credential dumps into
       exception strings, header repr() output, etc.

    The processor returns a *new* dict so the caller's event_dict is
    not mutated in place.
    """
    return _scrub_dict(event_dict)
