"""Tests for `llm_tracker.config.Settings` (ADR-0013 plugins_disabled parsing)."""

from __future__ import annotations

from llm_tracker.config import Settings


def test_plugins_disabled_default_empty(monkeypatch):
    """Without the env var, the denylist is an empty list — every plugin loads."""
    monkeypatch.delenv("LLMTRACK_PLUGINS_DISABLED", raising=False)
    assert Settings().plugins_disabled == []


def test_plugins_disabled_parses_csv_string():
    """A CSV passed in directly is split with whitespace trimmed."""
    s = Settings(plugins_disabled="token_counter, keyword_block")
    assert s.plugins_disabled == ["token_counter", "keyword_block"]


def test_plugins_disabled_strips_empty_entries():
    """Empty CSV slots collapse — `"a,,b,"` is two entries, not four."""
    s = Settings(plugins_disabled="a,,b,")
    assert s.plugins_disabled == ["a", "b"]


def test_plugins_disabled_passthrough_for_explicit_list():
    """Explicit list construction bypasses the CSV split (programmatic use)."""
    s = Settings(plugins_disabled=["foo", "bar"])
    assert s.plugins_disabled == ["foo", "bar"]


def test_plugins_disabled_reads_env(monkeypatch):
    """`LLMTRACK_PLUGINS_DISABLED=foo,bar` populates the field via pydantic-settings."""
    monkeypatch.setenv("LLMTRACK_PLUGINS_DISABLED", "foo, bar ,baz")
    s = Settings()
    assert s.plugins_disabled == ["foo", "bar", "baz"]
