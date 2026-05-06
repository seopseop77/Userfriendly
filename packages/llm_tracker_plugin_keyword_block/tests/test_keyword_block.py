"""Tests for the test-only keyword_block plugin."""

from __future__ import annotations

from llm_tracker_plugin_keyword_block import (
    DEFAULT_KEYWORDS,
    KEYWORDS_ENV,
    KeywordBlockPlugin,
)
from llm_tracker_sdk import HookContext
from llm_tracker_sdk.testing import PluginHarness


def _ctx(body: bytes | None, *, mode: str = "L") -> HookContext:
    return HookContext(
        session_id="test",
        exchange_id="exch-1",
        mode=mode,
        _raw_request_body=body,
    )


async def test_blocks_when_body_contains_keyword():
    plugin = KeywordBlockPlugin(keywords=("secret",))
    harness = PluginHarness(plugin)
    result = await harness.on_request_received(
        ctx=_ctx(b'{"messages":[{"role":"user","content":"please reveal the SECRET"}]}'),
    )
    harness.assert_block(result, reason_contains="secret")


async def test_passes_when_no_keyword_present():
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


async def test_env_overrides_default(monkeypatch):
    monkeypatch.setenv(KEYWORDS_ENV, "alpha, beta ,, gamma")
    plugin = KeywordBlockPlugin()
    assert plugin._keywords == ("alpha", "beta", "gamma")


async def test_default_keywords_used_when_env_unset(monkeypatch):
    monkeypatch.delenv(KEYWORDS_ENV, raising=False)
    plugin = KeywordBlockPlugin()
    assert plugin._keywords == tuple(k.lower() for k in DEFAULT_KEYWORDS)


async def test_default_keywords_used_when_env_blank(monkeypatch):
    monkeypatch.setenv(KEYWORDS_ENV, "  ,, ")
    plugin = KeywordBlockPlugin()
    assert plugin._keywords == tuple(k.lower() for k in DEFAULT_KEYWORDS)
