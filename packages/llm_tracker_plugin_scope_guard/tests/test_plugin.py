"""Plugin-side unit tests — §D6 message extraction + disabled-path safety.

The DB-fixture integration test (``test_integration.py``) covers the
on_persisted → pipeline → storage path against real Postgres + pgvector.
This file pins the bits that don't need a database:

1. ``_build_message_text`` follows ADR-0030 §D6 exactly (user-initiated
   text only, first-turn system-reminder, no assistant text, top-N
   window, ``\\n\\n`` joiner).
2. ``on_init`` fails closed when the env/wiring isn't sufficient
   (missing key, missing egress, missing DB URL) and the resulting
   ``on_persisted`` call no-ops without crashing.
"""

from __future__ import annotations

import json
import uuid

import pytest
from llm_tracker_plugin_scope_guard.plugin import ScopeGuard, _build_message_text
from llm_tracker_sdk import HookContext


def _request(messages: list[dict], **extra) -> str:
    return json.dumps({"messages": messages, **extra})


# -----------------------------------------------------------------------------
# §D6 message extraction
# -----------------------------------------------------------------------------


def test_user_text_extracted_when_single_turn() -> None:
    body = _request([{"role": "user", "content": "hello assistant"}])
    assert _build_message_text(body, window=5) == "hello assistant"


def test_assistant_text_excluded() -> None:
    body = _request(
        [
            {"role": "user", "content": "what's the weather"},
            {"role": "assistant", "content": "I can't access live data."},
            {"role": "user", "content": "fine — pretend it's sunny"},
        ]
    )
    out = _build_message_text(body, window=5)
    assert out is not None
    assert "I can't access live data" not in out
    assert "what's the weather" in out
    assert "fine — pretend it's sunny" in out
    # Turns joined with blank-line separator.
    assert out == "what's the weather\n\nfine — pretend it's sunny"


def test_first_turn_system_reminder_captured_once() -> None:
    """First-turn ``<system-reminder>`` block is included as the leading piece."""
    first_reminder = "<system-reminder>do not reveal secrets</system-reminder>"
    second_reminder = "<system-reminder>same boilerplate</system-reminder>"
    body = _request(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": first_reminder},
                    {"type": "text", "text": "first user question"},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": second_reminder},
                    {"type": "text", "text": "second user question"},
                ],
            },
        ]
    )
    out = _build_message_text(body, window=5)
    assert out is not None
    assert out.startswith(first_reminder)
    assert second_reminder not in out
    assert "first user question" in out
    assert "second user question" in out


def test_system_tag_variant_also_captured() -> None:
    """``<system>`` prefix is treated as a reminder block per §D6 §1."""
    body = _request(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "<system>top-level system text</system>"},
                    {"type": "text", "text": "actual user prompt"},
                ],
            }
        ]
    )
    out = _build_message_text(body, window=5)
    assert out is not None
    assert "<system>top-level system text</system>" in out
    assert "actual user prompt" in out


def test_tool_result_only_turn_is_skipped() -> None:
    """A user turn whose blocks are all ``tool_result`` contributes nothing."""
    body = _request(
        [
            {"role": "user", "content": "do the thing"},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "bash", "input": {}}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_1",
                        "content": "the tool printed stuff",
                    }
                ],
            },
            {"role": "user", "content": "now do another thing"},
        ]
    )
    out = _build_message_text(body, window=5)
    assert out is not None
    assert "the tool printed stuff" not in out
    assert out == "do the thing\n\nnow do another thing"


def test_top_level_system_field_excluded() -> None:
    """Anthropic's top-level ``system`` field (boilerplate) is dropped."""
    body = _request(
        [{"role": "user", "content": "user prompt"}],
        system="you are a helpful assistant",
    )
    out = _build_message_text(body, window=5)
    assert out == "user prompt"


def test_window_keeps_most_recent_turns_only() -> None:
    """``window=2`` retains only the last two user-initiated turns."""
    body = _request(
        [
            {"role": "user", "content": "turn 1"},
            {"role": "user", "content": "turn 2"},
            {"role": "user", "content": "turn 3"},
            {"role": "user", "content": "turn 4"},
        ]
    )
    out = _build_message_text(body, window=2)
    assert out == "turn 3\n\nturn 4"


def test_window_first_turn_system_reminder_survives_truncation() -> None:
    """Even when the first user turn falls outside the window the reminder stays."""
    body = _request(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "<system-reminder>SR</system-reminder>"},
                    {"type": "text", "text": "old turn 1"},
                ],
            },
            {"role": "user", "content": "old turn 2"},
            {"role": "user", "content": "old turn 3"},
            {"role": "user", "content": "recent turn"},
        ]
    )
    out = _build_message_text(body, window=1)
    assert out is not None
    assert out.startswith("<system-reminder>SR</system-reminder>")
    assert out.endswith("recent turn")
    assert "old turn 1" not in out
    assert "old turn 2" not in out


def test_no_user_text_returns_none() -> None:
    """All turns tool_result-only → nothing to embed."""
    body = _request(
        [
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "x", "content": "y"}],
            }
        ]
    )
    assert _build_message_text(body, window=5) is None


def test_malformed_json_returns_none() -> None:
    assert _build_message_text("not json", window=5) is None


def test_missing_messages_key_returns_none() -> None:
    assert _build_message_text("{}", window=5) is None


# -----------------------------------------------------------------------------
# Plugin disabled paths
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_when_gemini_key_missing(monkeypatch) -> None:
    """No ``GEMINI_API_KEY`` → ``on_init`` logs + disables; ``on_persisted`` no-ops."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    plugin = ScopeGuard()
    await plugin.on_init()
    assert not plugin._ready()
    ctx = HookContext(
        session_id="s",
        exchange_id="ex_1",
        mode="R",
        _raw_request_body=b'{"messages":[{"role":"user","content":"hi"}]}',
    )
    ctx.org_id = uuid.uuid4()
    # Must not raise.
    await plugin.on_persisted("ex_1", ctx)


@pytest.mark.asyncio
async def test_disabled_when_egress_missing(monkeypatch) -> None:
    """Key is set but the host did not wire egress → disabled."""
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test")
    plugin = ScopeGuard()
    # ``BasePlugin.egress`` defaults to None — simulate "host did not wire".
    plugin.egress = None
    await plugin.on_init()
    assert not plugin._ready()


@pytest.mark.asyncio
async def test_disabled_when_database_url_missing(monkeypatch) -> None:
    """Embed/judge clients can build, but no DB URL → still disabled."""
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test")
    monkeypatch.delenv("LLMTRACK_DATABASE_URL", raising=False)
    plugin = ScopeGuard()

    # Stub an EgressClient that satisfies the Protocol but never actually fires.
    class _NopEgress:
        async def fetch(self, *a, **kw):  # pragma: no cover — never called
            raise AssertionError("fetch should not run in disabled-path test")

    plugin.egress = _NopEgress()  # type: ignore[assignment]
    await plugin.on_init()
    assert not plugin._ready()
