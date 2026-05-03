"""Integration tests: PluginHost dispatches hooks and writes audit log entries."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from llm_tracker.plugin_host.host import PluginHost
from llm_tracker.storage.models import AuditLog, Base


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _audit_rows(factory) -> list[AuditLog]:
    async with factory() as session:
        return list((await session.execute(select(AuditLog))).scalars())


async def test_on_init_writes_proxy_started(session_factory):
    host = PluginHost(mode="L", session_factory=session_factory)
    await host.on_init()
    kinds = {r.kind for r in await _audit_rows(session_factory)}
    assert "proxy_started" in kinds


async def test_hook_invocations_logged(session_factory):
    host = PluginHost(mode="L", session_factory=session_factory)
    await host.on_request_received("xid-001")
    await host.before_forward("xid-001")
    await host.on_upstream_response_start("xid-001")
    await host.on_response_complete("xid-001")
    await host.on_persisted("xid-001")

    hooks = {r.hook for r in await _audit_rows(session_factory) if r.hook}
    assert hooks == {
        "on_request_received",
        "before_forward",
        "on_upstream_response_start",
        "on_response_complete",
        "on_persisted",
    }


async def test_on_shutdown_writes_proxy_stopped(session_factory):
    host = PluginHost(mode="L", session_factory=session_factory)
    await host.on_shutdown()
    kinds = {r.kind for r in await _audit_rows(session_factory)}
    assert "proxy_stopped" in kinds
