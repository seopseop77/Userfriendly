"""Tests for llm_tracker_sdk.testing (PluginHarness)."""

import pytest
from llm_tracker_sdk.hook_context import HookContext
from llm_tracker_sdk.hooks import Abort, Block, Pass, Transform
from llm_tracker_sdk.plugin import BasePlugin
from llm_tracker_sdk.testing import PluginHarness, make_exchange_id


class PassPlugin(BasePlugin):
    name = "pass_plugin"


class BlockPlugin(BasePlugin):
    name = "block_plugin"

    async def on_request_received(
        self, exchange_id: str, ctx: HookContext
    ) -> Pass | Block:
        return Block(reason="blocked: test")


class AbortPlugin(BasePlugin):
    name = "abort_plugin"

    async def on_response_chunk(
        self, exchange_id: str, chunk: bytes, ctx: HookContext
    ) -> Pass | Abort:
        return Abort(reason="aborted: test")


class TransformPlugin(BasePlugin):
    name = "transform_plugin"

    async def before_forward(
        self, exchange_id: str, ctx: HookContext
    ) -> Pass | Block | Transform:
        return Transform(headers={"x-test": "1"})


def test_make_exchange_id_unique():
    ids = {make_exchange_id() for _ in range(10)}
    assert len(ids) == 10
    assert all(id_.startswith("test-") for id_ in ids)


async def test_pass_plugin_passes():
    harness = PluginHarness(PassPlugin())
    await harness.init()
    harness.assert_pass(await harness.on_request_received())
    harness.assert_pass(await harness.before_forward())
    harness.assert_pass(await harness.on_upstream_response_start())
    harness.assert_pass(await harness.on_response_chunk(b"data"))


async def test_block_plugin():
    harness = PluginHarness(BlockPlugin())
    result = await harness.on_request_received()
    harness.assert_block(result, reason_contains="blocked")


async def test_abort_plugin():
    harness = PluginHarness(AbortPlugin())
    result = await harness.on_response_chunk(b"chunk")
    harness.assert_abort(result, reason_contains="aborted")


async def test_transform_plugin():
    harness = PluginHarness(TransformPlugin())
    result = await harness.before_forward()
    t = harness.assert_transform(result)
    assert t.headers == {"x-test": "1"}


async def test_assert_pass_fails_on_block():
    harness = PluginHarness(BlockPlugin())
    result = await harness.on_request_received()
    with pytest.raises(AssertionError, match="Expected Pass"):
        harness.assert_pass(result)
