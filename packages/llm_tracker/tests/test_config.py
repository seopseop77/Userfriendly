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


# -- ADR-0016: user_opted_in env knob ---------------------------------------


def test_user_opted_in_default_false(monkeypatch):
    """Off by default — ADR-0006's "explicit, never default" axiom."""
    monkeypatch.delenv("LLMTRACK_USER_OPTED_IN", raising=False)
    assert Settings().user_opted_in is False


def test_user_opted_in_truthy_env_values(monkeypatch):
    """pydantic-settings boolean coercion accepts 1/true/yes (case-insensitive)."""
    for raw in ("1", "true", "True", "yes", "YES"):
        monkeypatch.setenv("LLMTRACK_USER_OPTED_IN", raw)
        assert Settings().user_opted_in is True, f"failed for {raw!r}"


def test_user_opted_in_falsy_env_values(monkeypatch):
    """0/false/no stay False; whitespace and empty likewise."""
    for raw in ("0", "false", "False", "no", "NO"):
        monkeypatch.setenv("LLMTRACK_USER_OPTED_IN", raw)
        assert Settings().user_opted_in is False, f"failed for {raw!r}"
