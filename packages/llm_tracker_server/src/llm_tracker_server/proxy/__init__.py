"""Server-side proxy package (CP7+).

CP7 establishes the Anthropic credential pass-through edge of ADR-0020
(Axis 2): the server forwards the user's Anthropic credential header
on outbound calls to `api.anthropic.com` and **never** persists it.
The structlog scrub processor in `credential` is the last-line defense
against accidental leakage from any log call.

CP8 will port the full plugin host + SSE Tee + hook lifecycle from
`packages/llm_tracker/src/llm_tracker/proxy/` onto this same package.
For CP7 only the credential passthrough surface lives here.
"""

from .credential import (
    CREDENTIAL_HEADER_NAMES,
    REDACTED,
    is_credential_header,
    scrub_credential_processor,
)
from .forwarder import UPSTREAM_BASE, forward_request

__all__ = [
    "CREDENTIAL_HEADER_NAMES",
    "REDACTED",
    "UPSTREAM_BASE",
    "forward_request",
    "is_credential_header",
    "scrub_credential_processor",
]
