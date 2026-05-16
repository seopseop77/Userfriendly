"""String-level redaction for plugin-visible content (ADR-0029).

Applied inside :meth:`HookContext.request_text` and
:meth:`HookContext.response_content_json` so every plugin receives scrubbed
data automatically. The raw bytes on ``HookContext._raw_request_body`` and the
parsed dataclass on ``HookContext._parsed_response`` are left untouched -- the
storage layer keeps the canonical body, the scrubber only shapes what plugins
read at the accessor surface.

Pure: same input always produces the same output; no IO; no state.

Patterns covered (privacy-tilted -- favours over-redaction on ambiguity):

- ``sk-`` prefixed tokens (Anthropic / OpenAI API keys).
- ``lts_`` prefixed tokens (llm-tracker per-org bearer tokens, ADR-0020).
- ``Bearer <value>`` mentions (also captures the value half of an
  ``Authorization: Bearer <value>`` header echoed in a request or response
  body; the ``Authorization:`` prefix itself is not sensitive and is left in
  place).
- Email addresses (RFC 5322 subset; enough for most user-prompt mentions).

The structlog log-side scrubber in
:mod:`llm_tracker_server.proxy.credential` is a *separate* defence-in-depth
layer that redacts Anthropic credentials from log event dicts; this module
operates on raw text content destined for plugins.
"""

from __future__ import annotations

import re

_REDACTED = "[REDACTED:{kind}]"

# Order matters: bearer (which can wrap an ``sk-`` or ``lts_`` body) runs
# before the standalone token rules so the whole ``Bearer <value>`` span
# becomes one tag instead of ``Bearer [REDACTED:secret]``. Email last --
# the address never overlaps the earlier rules.
_BEARER_VALUE_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]+")
_SK_TOKEN_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
_LTS_TOKEN_RE = re.compile(r"\blts_[A-Za-z0-9_\-]{8,}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")


def scrub(text: str) -> str:
    """Redact secrets and PII from a plugin-visible text body.

    Used by :meth:`HookContext.request_text` and
    :meth:`HookContext.response_content_json`. Plugins never see the raw
    pattern matches; storage keeps the original bytes for operator
    investigation per ADR-0029.
    """
    text = _BEARER_VALUE_RE.sub(_REDACTED.format(kind="bearer"), text)
    text = _SK_TOKEN_RE.sub(_REDACTED.format(kind="secret"), text)
    text = _LTS_TOKEN_RE.sub(_REDACTED.format(kind="token"), text)
    text = _EMAIL_RE.sub(_REDACTED.format(kind="email"), text)
    return text
