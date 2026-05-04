"""Helper for writing exchange rows."""

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
