"""HostEgressClient: implements :class:`EgressClient` over :class:`EgressGuard` + httpx.

Ported verbatim from
:mod:`llm_tracker.egress_guard.client` (ADR-0015). The host owns the
shared :class:`httpx.AsyncClient` and constructs one
:class:`HostEgressClient` per loaded plugin at load time, baking in
the plugin's name. A plugin literally cannot mis-attribute an egress
-- every :meth:`fetch` flows through
``EgressGuard.check(plugin=self._plugin_name, ...)``.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx
from llm_tracker_sdk.egress import EgressClient, EgressDenied, EgressResponse

from .guard import EgressGuard


class HostEgressClient(EgressClient):
    """Per-plugin egress client.

    Lifetime is tied to the plugin (not the exchange). Background tasks
    in a plugin may call :meth:`fetch` long after the originating
    exchange has ended -- the audit-log attribution remains correct
    because the plugin name is bound here, not threaded through
    callers.

    The shared :class:`httpx.AsyncClient` is owned and torn down by
    :class:`~llm_tracker_server.plugin_host.host.PluginHost` during
    FastAPI ``lifespan`` exit, *after* every plugin's ``on_shutdown``
    has run, so a shutdown-time flusher can still complete its drain.
    """

    def __init__(
        self,
        *,
        plugin_name: str,
        guard: EgressGuard,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._plugin_name = plugin_name
        self._guard = guard
        self._http_client = http_client

    async def fetch(
        self,
        url: str,
        *,
        method: str = "POST",
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> EgressResponse:
        ok = await self._guard.check(
            plugin=self._plugin_name,
            url=url,
            capability="egress_http",
        )
        if not ok:
            # The guard already wrote the `egress_blocked` audit row;
            # raise so the plugin sees the denial in-band.
            raise EgressDenied(url=url, reason="denied_by_egress_guard")
        resp = await self._http_client.request(
            method,
            url,
            headers=dict(headers or {}),
            content=body,
            timeout=timeout,
        )
        return EgressResponse(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            body=resp.content,
        )
