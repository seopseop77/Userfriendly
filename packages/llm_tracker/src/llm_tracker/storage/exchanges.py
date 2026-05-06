"""Helpers for writing exchange rows."""

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Exchange


async def record_exchange_timing(
    session: AsyncSession,
    *,
    exchange_id: str,
    endpoint: str,
    t_request_received_ms: int,
    t_upstream_first_byte_ms: int,
    t_client_first_byte_ms: int,
) -> None:
    session.add(
        Exchange(
            id=exchange_id,
            session_id="local",
            started_at=t_request_received_ms,
            provider="anthropic",
            endpoint=endpoint,
            content_level="L0",
            tool_call_count=0,
            t_request_received_ms=t_request_received_ms,
            t_upstream_first_byte_ms=t_upstream_first_byte_ms,
            t_client_first_byte_ms=t_client_first_byte_ms,
        )
    )
    await session.commit()


async def record_exchange_blocked(
    session: AsyncSession,
    *,
    exchange_id: str,
    endpoint: str,
    blocked_by: str,
    started_at_ms: int,
) -> None:
    """Persist a row for a request that never reached the upstream.

    Used by the forwarder when a plugin's `on_request_received` or
    `before_forward` returns Block; `blocked_by` carries the plugin
    name so audits can attribute the decision.
    """
    session.add(
        Exchange(
            id=exchange_id,
            session_id="local",
            started_at=started_at_ms,
            provider="anthropic",
            endpoint=endpoint,
            content_level="L0",
            tool_call_count=0,
            t_request_received_ms=started_at_ms,
            blocked_by=blocked_by,
        )
    )
    await session.commit()
