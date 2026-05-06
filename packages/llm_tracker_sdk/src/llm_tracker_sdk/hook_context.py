"""Per-exchange context object handed to every plugin hook (ADR-0012).

The host constructs one `HookContext` per request and passes the
same instance to every per-exchange hook for that request. Plugins
read request/response data via lazy accessors (`ctx.request_text(level=...)`);
the accessor degrades the returned content based on the deployment
mode and the operator opt-in flag.

Plugins should not construct `HookContext` themselves; the host
owns its lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .levels import ContentLevel, degrade, effective_ceiling


@dataclass
class HookContext:
    """Per-exchange handle for plugin hooks.

    `session_id` and `exchange_id` identify the request slot.
    `mode` is the deployment mode (L / A / R) the host is running
    in; `user_opted_in` reflects per-task user consent and lifts
    the ceiling in Mode R only.

    The `_raw_request_body` slot is set by the host before
    dispatch; plugins read it via `request_text(level=...)`, which
    degrades to `min(level, effective_ceiling)` and returns `None`
    when the effective level falls to L0 (no plugin-visible
    content).
    """

    session_id: str
    exchange_id: str
    mode: str
    user_opted_in: bool = False
    _raw_request_body: bytes | None = field(default=None, repr=False)

    def effective_ceiling(self) -> ContentLevel:
        """The highest level this plugin may see, given mode + opt-in."""
        return effective_ceiling(self.mode, user_opted_in=self.user_opted_in)

    def request_text(self, level: ContentLevel = ContentLevel.L3) -> str | None:
        """Return the request body as text, degraded to `min(level, ceiling)`.

        Returns `None` when:
        - the effective level (`degrade(level, ceiling)`) is L0 — no
          plugin-visible content for this mode/opt-in combination;
        - the request body has not yet been provided to this context
          (e.g. a hook firing before the forwarder reads the body);
        - the body is not valid UTF-8 (the SDK doesn't speculate
          about non-text payloads).

        At L1 the host returns the raw text — Phase 1c will refine
        the per-level shape (e.g. L1 hash-only, L2 scrubbed). The
        primitive contract is "degrade-or-None" today; the
        per-level transform is wired plugin-by-plugin alongside
        `scope_guard`.
        """
        if self._raw_request_body is None:
            return None
        ceiling = self.effective_ceiling()
        effective = degrade(level, ceiling)
        if effective <= ContentLevel.L0:
            return None
        try:
            return self._raw_request_body.decode("utf-8")
        except UnicodeDecodeError:
            return None
