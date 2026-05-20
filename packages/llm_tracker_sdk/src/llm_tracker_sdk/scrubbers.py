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

JSON-aware mode: when the input parses as JSON (request bodies and the
extractor's assembled response JSON both do), the scrubber walks the parsed
structure and applies the regexes to each *decoded* string value, then
re-serialises. This avoids an orphan-backslash hazard observed live
2026-05-19 -- the email regex's ``\\b`` word boundary matched between a
literal ``\\`` and the ``t`` of a ``\\t`` JSON escape, consuming the ``t``
as the leading character of ``test_user@example.com``; the substitution
left the ``\\`` orphaned in front of ``[REDACTED:email]``, producing ``\\[``
which is not a valid JSON escape and broke any downstream ``::jsonb`` cast.
Operating on decoded values eliminates that class of corruption entirely.

The structlog log-side scrubber in
:mod:`llm_tracker_server.proxy.credential` is a *separate* defence-in-depth
layer that redacts Anthropic credentials from log event dicts; this module
operates on raw text content destined for plugins.
"""

from __future__ import annotations

import json
import re
from typing import Any

_REDACTED = "[REDACTED:{kind}]"

# Order matters: bearer (which can wrap an ``sk-`` or ``lts_`` body) runs
# before the standalone token rules so the whole ``Bearer <value>`` span
# becomes one tag instead of ``Bearer [REDACTED:secret]``. Email last --
# the address never overlaps the earlier rules.
_BEARER_VALUE_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]+")
_SK_TOKEN_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
_LTS_TOKEN_RE = re.compile(r"\blts_[A-Za-z0-9_\-]{8,}\b")
# Local part + non-TLD domain use ``\w`` (Python 3 Unicode-aware) so
# umlauted local parts (``ünîcödé@``) and raw IDN domains (``münchen.de``)
# both redact. TLD stays ``[A-Za-z]{2,}`` -- the ASCII constraint blocks
# a ``1.2``-style false positive and covers the punycode wire format
# (``xn--mnchen-3ya.de``); raw Unicode-TLD shapes (``example.中国``) are
# rare enough in user prompts to defer per the privacy-tilted scope.
_EMAIL_RE = re.compile(r"\b[\w.%+\-]+@[\w.\-]+\.[A-Za-z]{2,}\b")


def scrub(text: str) -> str:
    """Redact secrets and PII from a plugin-visible text body.

    Used by :meth:`HookContext.request_text` and
    :meth:`HookContext.response_content_json`. Plugins never see the raw
    pattern matches; storage keeps the original bytes for operator
    investigation per ADR-0029.

    Tries a JSON-aware pass first (parse -> scrub decoded strings ->
    re-serialise) and falls back to flat-text scrubbing when the input is
    not JSON. The JSON-aware pass is what keeps the regexes from chewing
    half of a ``\\t`` / ``\\n`` escape and leaving an orphan backslash that
    would invalidate the output for any downstream ``::jsonb`` consumer.
    """
    if text and text[:1] in ("{", "["):
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            pass
        else:
            scrubbed = _scrub_value(parsed)
            # ensure_ascii=False keeps non-ASCII (Korean, etc.) human-readable
            # and byte-compact. separators=(',', ':') matches Anthropic's
            # serialisation closely enough that downstream consumers (cache
            # keys, dedup hashes) don't see noisy whitespace drift.
            return json.dumps(scrubbed, ensure_ascii=False, separators=(",", ":"))
    return _scrub_text(text)


def _scrub_text(text: str) -> str:
    text = _BEARER_VALUE_RE.sub(_REDACTED.format(kind="bearer"), text)
    text = _SK_TOKEN_RE.sub(_REDACTED.format(kind="secret"), text)
    text = _LTS_TOKEN_RE.sub(_REDACTED.format(kind="token"), text)
    text = _EMAIL_RE.sub(_REDACTED.format(kind="email"), text)
    return text


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(v) for v in value]
    return value
