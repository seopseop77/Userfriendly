"""Per-exchange context object handed to every plugin hook (ADR-0012).

The host constructs one `HookContext` per request and passes the
same instance to every per-exchange hook for that request. Plugins
read request/response data via lazy accessors; the accessor degrades
the returned content based on the deployment mode and the operator
opt-in flag.

Per-level shape of the request-side accessors (design.md §7.1):

| Effective level | `request_text()` | `request_hash()` | `request_length()` |
|---|---|---|---|
| L0 | None              | None             | None               |
| L1 | None              | hex SHA-256      | byte length        |
| L2 | scrubbed text     | hex SHA-256      | byte length        |
| L3 | scrubbed text     | hex SHA-256      | byte length        |

Plugin-visible request text and response JSON pass through
:func:`llm_tracker_sdk.scrubbers.scrub` before being returned (ADR-0029).
The raw bytes on ``_raw_request_body`` and the parsed response on
``_parsed_response`` stay untouched **in memory** during the request
lifetime; whether the canonical body reaches disk depends on the write
path. The server core writes ``public.exchanges`` with metadata only
(no body columns). The ``analytics_sink`` plugin writes
``public.plugin_analytics`` by reading through these accessors, so
plugin-mediated rows inherit the scrubbed shape -- the privacy floor is
the accessor *and* the storage ceiling for plugin-written tables. See
ADR-0029 §"Axis 6" for the canonical-body / accessor trade-off.

Plugins should not construct `HookContext` themselves; the host
owns its lifecycle.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

from .egress import EgressClient
from .levels import ContentLevel, degrade, effective_ceiling
from .scrubbers import scrub


@dataclass
class HookContext:
    """Per-exchange handle for plugin hooks.

    `session_id` and `exchange_id` identify the request slot.
    `mode` is the deployment mode (L / A / R) the host is running
    in; `user_opted_in` reflects per-task user consent and lifts
    the ceiling in Mode R only.

    The `_raw_request_body` slot is set by the host before
    dispatch; plugins read it via `request_text(level=...)`,
    `request_hash()`, and `request_length()`. Each accessor
    returns `None` when the data is not available at the
    plugin's effective ceiling.
    """

    session_id: str
    exchange_id: str
    mode: str
    user_opted_in: bool = False
    egress: EgressClient | None = None
    # ADR-0026: tenancy axis for server-side plugins that write to
    # org-scoped tables (e.g. ``analytics_sink``). The forwarder sets
    # this in ``begin_exchange`` from ``request.state.org_id``. Stays
    # ``None`` on the local-sidecar path; plugins that need it must
    # guard against ``None``.
    org_id: uuid.UUID | None = None
    _raw_request_body: bytes | None = field(default=None, repr=False)
    # ADR-0019 §Open questions / CP10: per-plugin clamp set by the
    # server-side host from the plugin manifest's ``min_content_level``.
    # When non-None it wins over the mode/opt-in math below — the
    # local-sidecar path (mode L/A/R) leaves it ``None`` so legacy
    # callers keep their existing ceiling semantics.
    _ceiling: ContentLevel | None = field(default=None, repr=False)
    # ADR-0026: the server core sets this after `parse_sse_stream`
    # finishes. Typed as ``object`` (not ``ParsedResponse``) so the SDK
    # does not import from the server package — plugins read structured
    # data via the ``response_usage()`` / ``response_content_json()``
    # accessors below, which know the concrete shape.
    _parsed_response: object | None = field(default=None, repr=False)

    def effective_ceiling(self) -> ContentLevel:
        """The highest level this plugin may see.

        If the host pinned a manifest-driven ``_ceiling`` it wins
        outright (ADR-0019). Otherwise the legacy mode + opt-in math
        is used so the local-sidecar host keeps working unchanged.
        """
        if self._ceiling is not None:
            return self._ceiling
        return effective_ceiling(self.mode, user_opted_in=self.user_opted_in)

    def request_text(self, level: ContentLevel = ContentLevel.L3) -> str | None:
        """Return the request body as text, degraded to `min(level, ceiling)`.

        Returns `None` when:
        - the effective level (`degrade(level, ceiling)`) is L0 or L1 —
          neither tier exposes the raw body. L1 plugins read
          `request_hash()` / `request_length()` instead;
        - the request body has not yet been provided to this context
          (e.g. a hook firing before the forwarder reads the body);
        - the body is not valid UTF-8 (the SDK doesn't speculate
          about non-text payloads).

        At both L2 and L3 the host runs the decoded body through
        :func:`llm_tracker_sdk.scrubbers.scrub` before returning so
        plugins never read raw secrets or PII directly (ADR-0029). The
        canonical bytes live on ``_raw_request_body`` and reach the
        storage layer unchanged.
        """
        if self._raw_request_body is None:
            return None
        ceiling = self.effective_ceiling()
        effective = degrade(level, ceiling)
        if effective <= ContentLevel.L1:
            return None
        try:
            decoded = self._raw_request_body.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return scrub(decoded)

    def request_hash(self) -> str | None:
        """Hex SHA-256 of the raw request bytes.

        Returns `None` when the effective ceiling is below L1 (Mode A
        denies even hashes) or when no request body has been provided
        to this context yet. Plugins use this to fingerprint a body
        without ever seeing its contents — the L1 escape hatch for
        deduplication and "did this exact prompt repeat" checks.
        """
        if self._raw_request_body is None:
            return None
        if self.effective_ceiling() < ContentLevel.L1:
            return None
        return hashlib.sha256(self._raw_request_body).hexdigest()

    def request_length(self) -> int | None:
        """Byte length of the raw request body.

        Returns `None` under the same conditions as `request_hash()`:
        below-L1 ceiling or absent body. Length is metadata that
        belongs to L1+ alongside the hash; Mode A (L0 ceiling) does
        not expose it.
        """
        if self._raw_request_body is None:
            return None
        if self.effective_ceiling() < ContentLevel.L1:
            return None
        return len(self._raw_request_body)

    def response_usage(self) -> object | None:
        """Return the extractor's `ResponseUsage`, or `None` if not yet parsed.

        ADR-0026 Option B: the server core's `parse_sse_stream` populates
        `_parsed_response` on stream completion; plugins that run in
        `on_persisted` read the usage block (model_served + token counts
        + stop_reason) via this accessor. The return type is `object`
        rather than `ResponseUsage` so the SDK does not import from the
        server package; plugins that want typing should
        ``from llm_tracker_server.extractors.anthropic import ResponseUsage``
        under ``if TYPE_CHECKING:``.
        """
        if self._parsed_response is None:
            return None
        return getattr(self._parsed_response, "usage", None)

    def response_content_json(self) -> str | None:
        """Return the assembled response body as a JSON string, or `None`.

        The JSON mirrors the non-stream Anthropic shape:
        ``{"model": ..., "content": [{"type": "text", "text": "..."}],
        "stop_reason": ..., "usage": {...}}``. Returns `None` when the
        extractor has not run on this exchange (e.g. blocked path,
        pre-SSE upstream failure).

        Pipes through :func:`llm_tracker_sdk.scrubbers.scrub` before
        returning so plugin-visible response content is redacted in line
        with ADR-0029. The original JSON string on
        ``_parsed_response.response_json`` is left untouched -- the
        storage layer reads the canonical body, the scrubber only shapes
        what plugins observe.
        """
        if self._parsed_response is None:
            return None
        value = getattr(self._parsed_response, "response_json", None)
        if value is None:
            return None
        return scrub(value)
