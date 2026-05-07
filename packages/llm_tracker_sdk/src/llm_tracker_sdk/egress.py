"""Egress client SDK API (ADR-0015).

Plugins call `await ctx.egress.fetch(url, ...)` from inside hooks, or
`await self.egress.fetch(url, ...)` from background tasks (queues,
flushers, retry workers). Both reads return the same `EgressClient`
instance — the host binds one per loaded plugin at load time, with the
plugin's name baked in for audit-log attribution.

Direct use of `httpx`, `requests`, raw sockets, etc. from plugin code
is forbidden by `docs/plugins.md §8` and ADR-0006. This module is the
sanctioned path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EgressResponse:
    """Outcome of a successful `EgressClient.fetch`.

    The body is materialised in full; streaming is intentionally out of
    scope for v0.1 (ADR-0015 §Open questions).
    """

    status_code: int
    headers: Mapping[str, str]
    body: bytes


class EgressDenied(Exception):
    """Raised by `EgressClient.fetch` when EgressGuard denies the call.

    The guard has already written the `egress_blocked` audit row by the
    time this is raised, so the plugin can handle the denial in-band
    without an extra DB read.
    """

    def __init__(self, *, url: str, reason: str) -> None:
        super().__init__(f"egress denied for {url}: {reason}")
        self.url = url
        self.reason = reason


class EgressClient(Protocol):
    """Host-mediated outbound HTTP for plugins (ADR-0015).

    The plugin's identity is bound to the client at construction time;
    every `fetch` is attributed to that plugin in the audit log. A
    plugin literally cannot call out as someone else.

    Lifetime: per-plugin, populated on `BasePlugin.egress` at plugin
    load. `HookContext.egress` references the same instance for
    in-hook ergonomics. Background tasks should hold `self.egress`
    directly so they survive past their triggering exchange.
    """

    async def fetch(
        self,
        url: str,
        *,
        method: str = "POST",
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> EgressResponse: ...
