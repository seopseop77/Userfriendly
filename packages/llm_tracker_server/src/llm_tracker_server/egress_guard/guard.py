"""EgressGuard: manifest allowlist + audit trail for plugin egress.

CP8 port of the local-sidecar
:mod:`llm_tracker.egress_guard.guard.EgressGuard` with two shape
changes mandated by ADR-0019:

* ``mode=`` is dropped. The L/A/R deployment-mode taxonomy was retired
  in ADR-0019 §Decision item 1; the previously mode-keyed denial
  branches (``mode_L_denies_egress``,
  ``mode_X_not_in_allowed_modes``,
  ``mode_A_requires_single_destination``) are gone too. The guard
  enforces only what the plugin's own manifest declared.
* The audit writer is injected as a callable instead of opening a
  brand-new session from a session factory. CP9 will wire the
  production writer through the request-scoped session so audit rows
  carry ``org_id`` from ``request.state.org_id``; for CP8 the host
  ships a no-op writer by default so the guard runs without storage
  access.

Decision flow on :meth:`check`:

1. The plugin must have a manifest registered via :meth:`register`.
2. The requested capability must be declared in
   ``manifest.capabilities``.
3. The destination URL must exact-match an entry in
   ``manifest.egress_destinations`` (no wildcards).

Every check emits an ``egress_attempt`` (allow) or ``egress_blocked``
(deny) audit-log entry through the injected writer.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from llm_tracker_sdk.manifest import PluginManifest

# Audit-row writer contract. Keyword-only fields mirror the local
# sidecar's ``write_audit`` helper so CP9 can hand in a session-bound
# writer without changing the call site. The default lives in
# :func:`_noop_audit_writer` below.
AuditWriter = Callable[..., Awaitable[None]]


async def _noop_audit_writer(**_kwargs: object) -> None:
    """Default audit writer for CP8: discard the row.

    CP9 replaces this with a writer that uses the per-request
    ``AsyncSession`` (already bound to ``app.org_id`` by the auth
    middleware) and writes an :class:`~llm_tracker_server.storage.AuditLog`
    row whose ``org_id`` matches the caller's org. The audit *call
    sites* land here in CP8 so the diff CP9 needs is minimal.
    """
    return None


class EgressGuard:
    """Per-plugin egress allowlist + audit trail.

    Parameters
    ----------
    audit_writer:
        Async callable invoked once per :meth:`check`. Receives
        keyword-only fields (``kind``, ``plugin``, ``capability``,
        ``destination``, ``outcome``, ``detail_json``). Defaults to
        :func:`_noop_audit_writer` so the guard is usable in tests and
        in pre-CP9 lifespan wiring without storage access.
    """

    def __init__(self, *, audit_writer: AuditWriter | None = None) -> None:
        self._audit_writer: AuditWriter = audit_writer or _noop_audit_writer
        self._manifests: dict[str, PluginManifest] = {}

    def register(self, manifest: PluginManifest) -> None:
        """Register a plugin's manifest so the guard can look it up by name."""
        self._manifests[manifest.name] = manifest

    async def check(
        self,
        *,
        plugin: str,
        url: str,
        capability: str = "egress_http",
    ) -> bool:
        """Return ``True`` iff egress is allowed. Always audit-logs the attempt."""
        reason = self._evaluate(plugin=plugin, url=url, capability=capability)
        allowed = reason is None

        detail: dict[str, object] = {}
        if reason is not None:
            detail["reason"] = reason

        await self._audit_writer(
            kind="egress_attempt" if allowed else "egress_blocked",
            plugin=plugin,
            capability=capability,
            destination=url,
            outcome="ok" if allowed else "denied",
            detail_json=json.dumps(detail) if detail else None,
        )
        return allowed

    def _evaluate(self, *, plugin: str, url: str, capability: str) -> str | None:
        """Return ``None`` if allowed, else a short string describing why it was denied."""
        manifest = self._manifests.get(plugin)
        if manifest is None:
            return "no_manifest_registered"
        if capability not in manifest.capabilities:
            return f"capability_not_declared:{capability}"
        if url not in manifest.egress_destinations:
            return "destination_not_in_allowlist"
        return None
