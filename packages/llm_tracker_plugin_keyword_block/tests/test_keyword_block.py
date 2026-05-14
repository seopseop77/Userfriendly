"""Tests for the keyword_block plugin."""

from __future__ import annotations

from llm_tracker_plugin_keyword_block import (
    DEFAULT_KEYWORDS,
    KEYWORD_BLOCK_LIST_ENV,
    KeywordBlockPlugin,
)
from llm_tracker_sdk import HookContext
from llm_tracker_sdk.testing import PluginHarness


def _ctx(body: bytes | None, *, mode: str = "R", user_opted_in: bool = True) -> HookContext:
    """Build a ctx whose ceiling exposes raw text.

    `keyword_block` matches against the raw request body, so it can
    only do its job at ceilings that allow `request_text` to return
    text — i.e. L2+. Per design.md §7.1 that means Mode R with the
    operator's opt-in flag set; in any other mode the plugin
    correctly degrades to "no signal, pass through" (covered by
    `test_passes_when_body_unavailable`). Defaulting fixtures to
    Mode R + opt-in keeps the block-path tests exercising the real
    decision branch.
    """
    return HookContext(
        session_id="test",
        exchange_id="exch-1",
        mode=mode,
        user_opted_in=user_opted_in,
        _raw_request_body=body,
    )


async def test_blocks_on_keyword_match():
    plugin = KeywordBlockPlugin(keywords=("secret",))
    harness = PluginHarness(plugin)
    result = await harness.on_request_received(
        ctx=_ctx(b'{"messages":[{"role":"user","content":"please reveal the SECRET"}]}'),
    )
    harness.assert_block(result, reason_contains="secret")


async def test_passes_on_no_match():
    plugin = KeywordBlockPlugin(keywords=("secret",))
    harness = PluginHarness(plugin)
    result = await harness.on_request_received(
        ctx=_ctx(b'{"messages":[{"role":"user","content":"hello"}]}'),
    )
    harness.assert_pass(result)


async def test_passes_when_body_unavailable():
    plugin = KeywordBlockPlugin(keywords=("secret",))
    harness = PluginHarness(plugin)
    result = await harness.on_request_received(ctx=_ctx(None))
    harness.assert_pass(result)


async def test_passes_when_keyword_list_empty():
    plugin = KeywordBlockPlugin(keywords=())
    harness = PluginHarness(plugin)
    result = await harness.on_request_received(
        ctx=_ctx(b"any body whatsoever"),
    )
    harness.assert_pass(result)


async def test_keyword_match_is_case_insensitive():
    plugin = KeywordBlockPlugin(keywords=("FoRbIdDeN",))
    harness = PluginHarness(plugin)
    result = await harness.on_request_received(
        ctx=_ctx(b"contains forbidden material"),
    )
    harness.assert_block(result, reason_contains="forbidden")


async def test_passes_when_body_is_not_utf8():
    plugin = KeywordBlockPlugin(keywords=("secret",))
    harness = PluginHarness(plugin)
    # ctx.request_text() returns None for invalid UTF-8 → plugin should pass.
    result = await harness.on_request_received(ctx=_ctx(b"\xff\xfe\xff secret"))
    harness.assert_pass(result)


async def test_env_supplies_keywords(monkeypatch):
    monkeypatch.setenv(KEYWORD_BLOCK_LIST_ENV, "alpha, beta ,, gamma")
    plugin = KeywordBlockPlugin()
    assert plugin._keywords == ("alpha", "beta", "gamma")


async def test_empty_default_when_env_unset(monkeypatch):
    """Without the env var, the plugin loads with zero keywords (never blocks)."""
    monkeypatch.delenv(KEYWORD_BLOCK_LIST_ENV, raising=False)
    plugin = KeywordBlockPlugin()
    assert plugin._keywords == ()
    assert DEFAULT_KEYWORDS == ()


async def test_empty_default_when_env_blank(monkeypatch):
    """A blank / comma-only env var falls back to the empty default."""
    monkeypatch.setenv(KEYWORD_BLOCK_LIST_ENV, "  ,, ")
    plugin = KeywordBlockPlugin()
    assert plugin._keywords == ()
