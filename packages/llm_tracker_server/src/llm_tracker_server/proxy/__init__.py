"""Server-side proxy package (CP7 credential edge + CP8 plugin host wiring).

CP7 established the Anthropic credential pass-through edge of
ADR-0020 (Axis 2): the server forwards the user's Anthropic credential
header on outbound calls to ``api.anthropic.com`` and **never**
persists it. CP8 layers the 8-hook plugin lifecycle around that
forwarder so a server-side ``PluginHost`` can ``Block`` / ``Transform``
/ ``Abort`` an exchange and so the synthetic SSE block stream from
ADR-0002 §3 replaces the upstream response when a plugin denies the
request.
"""

from .credential import (
    CREDENTIAL_HEADER_NAMES,
    REDACTED,
    is_credential_header,
    scrub_credential_processor,
)
from .forwarder import UPSTREAM_BASE, forward_request
from .sse import block_response, block_sse_chunks

__all__ = [
    "CREDENTIAL_HEADER_NAMES",
    "REDACTED",
    "UPSTREAM_BASE",
    "block_response",
    "block_sse_chunks",
    "forward_request",
    "is_credential_header",
    "scrub_credential_processor",
]
