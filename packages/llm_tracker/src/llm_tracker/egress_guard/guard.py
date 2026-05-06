"""EgressGuard enforces the egress allowlist and audit-logs every attempt."""

import json

from llm_tracker_sdk.manifest import PluginManifest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..storage.audit import write_audit


class EgressGuard:
    """Per-plugin egress allowlist with mode-based capability policy.

    Decision flow on `check()` (design.md §7.3, §8):
      1. Mode L denies all plugin egress, regardless of manifest.
      2. The plugin must have a manifest registered via `register()`.
      3. The current mode must appear in `manifest.allowed_modes`.
      4. The requested capability must be declared in `manifest.capabilities`.
      5. The destination URL must exact-match an entry in
         `manifest.egress_destinations` (no wildcards).
      6. In Mode A only one destination may be declared (operator-approved
         single destination per design.md §8).

    Every check writes an `egress_attempt` (allow) or `egress_blocked` (deny)
    entry to the audit log, including the mode and -- on denial -- the reason.
    """

    def __init__(
        self,
        mode: str,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.mode = mode
        self._session_factory = session_factory
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
        """Returns True iff egress is allowed. Always audit-logs the attempt."""
        reason = self._evaluate(plugin=plugin, url=url, capability=capability)
        allowed = reason is None

        detail = {"mode": self.mode}
        if reason is not None:
            detail["reason"] = reason

        async with self._session_factory() as session:
            await write_audit(
                session,
                kind="egress_attempt" if allowed else "egress_blocked",
                plugin=plugin,
                capability=capability,
                destination=url,
                outcome="ok" if allowed else "denied",
                detail_json=json.dumps(detail),
            )
        return allowed

    def _evaluate(self, *, plugin: str, url: str, capability: str) -> str | None:
        """Return None if allowed, else a short string describing why it was denied."""
        if self.mode == "L":
            return "mode_L_denies_egress"

        manifest = self._manifests.get(plugin)
        if manifest is None:
            return "no_manifest_registered"
        if self.mode not in manifest.allowed_modes:
            return f"mode_{self.mode}_not_in_allowed_modes"
        if capability not in manifest.capabilities:
            return f"capability_not_declared:{capability}"
        if url not in manifest.egress_destinations:
            return "destination_not_in_allowlist"
        if self.mode == "A" and len(manifest.egress_destinations) != 1:
            return "mode_A_requires_single_destination"
        return None
