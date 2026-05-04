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

from .hooks import Abort, Block, Pass, Transform
from .plugin import BasePlugin


def make_exchange_id() -> str:
    return f"test-{uuid.uuid4()}"


class PluginHarness:
    """Wraps a BasePlugin and provides helpers for testing hook invocations."""

    def __init__(self, plugin: BasePlugin) -> None:
        self.plugin = plugin

    async def init(self) -> None:
        await self.plugin.on_init()

    async def shutdown(self) -> None:
        await self.plugin.on_shutdown()

    async def on_request_received(self, exchange_id: str | None = None) -> Pass | Block:
        return await self.plugin.on_request_received(exchange_id or make_exchange_id())

    async def before_forward(self, exchange_id: str | None = None) -> Pass | Block | Transform:
        return await self.plugin.before_forward(exchange_id or make_exchange_id())

    async def on_upstream_response_start(self, exchange_id: str | None = None) -> Pass | Abort:
        return await self.plugin.on_upstream_response_start(exchange_id or make_exchange_id())

    async def on_response_chunk(
        self,
        chunk: bytes = b"",
        exchange_id: str | None = None,
    ) -> Pass | Abort:
        return await self.plugin.on_response_chunk(exchange_id or make_exchange_id(), chunk)

    async def on_response_complete(self, exchange_id: str | None = None) -> None:
        await self.plugin.on_response_complete(exchange_id or make_exchange_id())

    async def on_persisted(self, exchange_id: str | None = None) -> None:
        await self.plugin.on_persisted(exchange_id or make_exchange_id())

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
