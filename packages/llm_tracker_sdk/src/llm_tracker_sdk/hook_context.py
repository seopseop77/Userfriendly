"""Per-exchange context object handed to every plugin hook (ADR-0012).

The host constructs one `HookContext` per request and passes the
same instance to every per-exchange hook for that request. Plugins
read request/response data via lazy accessors; the accessor degrades
the returned content based on the deployment mode and the operator
opt-in flag.

Per-level shape of the request-side accessors (design.md §7.1):

| Effective level | `request_text()` | `request_hash()` | `request_length()` |
|---|---|---|---|
| L0 | None             | None             | None               |
| L1 | None             | hex SHA-256      | byte length        |
| L2 | raw decoded text | hex SHA-256      | byte length        |
| L3 | raw decoded text | hex SHA-256      | byte length        |

L2 returns the raw decoded text today. The "scrubbed" shape promised
by §7.1 lands in Phase 1c alongside the scrubber primitives; the
deferral is tracked under STATUS.md "Phase 1c prerequisites" and
ADR-0006 §"Open questions".

Plugins should not construct `HookContext` themselves; the host
owns its lifecycle.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .egress import EgressClient
from .levels import ContentLevel, degrade, effective_ceiling


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
    _raw_request_body: bytes | None = field(default=None, repr=False)

    def effective_ceiling(self) -> ContentLevel:
        """The highest level this plugin may see, given mode + opt-in."""
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

        At L2 the host returns the raw decoded text; the scrubbed
        shape promised by design.md §7.1 lands in Phase 1c alongside
        the scrubber primitives. At L3 raw text is returned as-is.
        """
        if self._raw_request_body is None:
            return None
        ceiling = self.effective_ceiling()
        effective = degrade(level, ceiling)
        if effective <= ContentLevel.L1:
            return None
        try:
            return self._raw_request_body.decode("utf-8")
        except UnicodeDecodeError:
            return None

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
