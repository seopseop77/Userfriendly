"""Test harness for plugin authors.

Usage::

    from llm_tracker_sdk.testing import PluginHarness
    from my_plugin import MyPlugin

    async def test_blocks_bad_request():
        harness = PluginHarness(MyPlugin())
        await harness.init()
        result = await harness.on_request_received()
        harness.assert_block(result, reason_contains="out of scope")
"""

from __future__ import annotations

import uuid

from .hook_context import HookContext
from .hooks import Abort, Block, Pass, Transform
from .plugin import BasePlugin


def make_exchange_id() -> str:
    return f"test-{uuid.uuid4()}"


def _default_ctx(
    exchange_id: str,
    *,
    mode: str = "L",
    request_body: bytes | None = None,
) -> HookContext:
    """Build a HookContext with sensible defaults for harness tests."""
    return HookContext(
        session_id="test",
        exchange_id=exchange_id,
        mode=mode,
        _raw_request_body=request_body,
    )


class PluginHarness:
    """Wraps a BasePlugin and provides helpers for testing hook invocations.

    Each invocation builds a default `HookContext` (mode="L", no request
    body). Callers that need to exercise content-level degradation can
    pass an explicit `ctx=` kwarg or construct their own `HookContext`
    via `llm_tracker_sdk.HookContext`.
    """

    def __init__(self, plugin: BasePlugin) -> None:
        self.plugin = plugin

    async def init(self) -> None:
        await self.plugin.on_init()

    async def shutdown(self) -> None:
        await self.plugin.on_shutdown()

    async def on_request_received(
        self,
        exchange_id: str | None = None,
        *,
        ctx: HookContext | None = None,
    ) -> Pass | Block:
        eid = exchange_id or make_exchange_id()
        return await self.plugin.on_request_received(eid, ctx or _default_ctx(eid))

    async def before_forward(
        self,
        exchange_id: str | None = None,
        *,
        ctx: HookContext | None = None,
    ) -> Pass | Block | Transform:
        eid = exchange_id or make_exchange_id()
        return await self.plugin.before_forward(eid, ctx or _default_ctx(eid))

    async def on_upstream_response_start(
        self,
        exchange_id: str | None = None,
        *,
        ctx: HookContext | None = None,
    ) -> Pass | Abort:
        eid = exchange_id or make_exchange_id()
        return await self.plugin.on_upstream_response_start(eid, ctx or _default_ctx(eid))

    async def on_response_chunk(
        self,
        chunk: bytes = b"",
        exchange_id: str | None = None,
        *,
        ctx: HookContext | None = None,
    ) -> Pass | Abort:
        eid = exchange_id or make_exchange_id()
        return await self.plugin.on_response_chunk(eid, chunk, ctx or _default_ctx(eid))

    async def on_response_complete(
        self,
        exchange_id: str | None = None,
        *,
        ctx: HookContext | None = None,
    ) -> None:
        eid = exchange_id or make_exchange_id()
        await self.plugin.on_response_complete(eid, ctx or _default_ctx(eid))

    async def on_persisted(
        self,
        exchange_id: str | None = None,
        *,
        ctx: HookContext | None = None,
    ) -> None:
        eid = exchange_id or make_exchange_id()
        await self.plugin.on_persisted(eid, ctx or _default_ctx(eid))

    # -- assertion helpers --------------------------------------------------

    @staticmethod
    def assert_pass(result: object) -> None:
        assert isinstance(result, Pass), f"Expected Pass, got {result!r}"

    @staticmethod
    def assert_block(result: object, *, reason_contains: str | None = None) -> None:
        assert isinstance(result, Block), f"Expected Block, got {result!r}"
        if reason_contains is not None:
            assert reason_contains in result.reason, (
                f"Block reason {result.reason!r} does not contain {reason_contains!r}"
            )

    @staticmethod
    def assert_transform(result: object) -> Transform:
        assert isinstance(result, Transform), f"Expected Transform, got {result!r}"
        return result

    @staticmethod
    def assert_abort(result: object, *, reason_contains: str | None = None) -> None:
        assert isinstance(result, Abort), f"Expected Abort, got {result!r}"
        if reason_contains is not None:
            assert reason_contains in result.reason, (
                f"Abort reason {result.reason!r} does not contain {reason_contains!r}"
            )
