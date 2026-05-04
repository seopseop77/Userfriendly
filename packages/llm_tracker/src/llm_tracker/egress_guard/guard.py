"""EgressGuard enforces the egress allowlist and audit-logs every attempt."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..storage.audit import write_audit


class EgressGuard:
    """Phase-0 skeleton: denies all plugin egress; allows only the LLM upstream (core path).

    Phase 1b wires per-plugin manifest allowlists and mode-based capability checks.
    """

    def __init__(self, mode: str, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.mode = mode
        self._session_factory = session_factory

    async def check(
        self,
        *,
        plugin: str,
        url: str,
        capability: str = "egress_http",
    ) -> bool:
        """Returns True if egress is allowed. Always writes an audit entry."""
        # Phase 0: deny all plugin egress regardless of mode.
        # Phase 1b replaces this with per-plugin manifest allowlist checks.
        allowed = False
        async with self._session_factory() as session:
            await write_audit(
                session,
                kind="egress_attempt" if allowed else "egress_blocked",
                plugin=plugin,
                capability=capability,
                destination=url,
                outcome="ok" if allowed else "denied",
            )
        return allowed
