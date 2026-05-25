"""Unit tests for `canonical_message`.

Test plan from `docs/worklog/2026-05-19-candidate-1-handoff.md` §3.
"""

from __future__ import annotations

from llm_tracker_plugin_analytics_sink.normalize import canonical_message


def test_drops_cache_control_from_every_block() -> None:
    """Rule A: `cache_control` is stripped from every block; other
    keys on those blocks remain untouched.
    """
    msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "b", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "c"},
        ],
    }
    out = canonical_message(msg)
    # Three blocks survive; the middle one no longer carries cache_control.
    assert out == {
        "role": "user",
        "content": [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "b"},
            {"type": "text", "text": "c"},
        ],
    }


def test_collapses_single_text_block_to_string() -> None:
    """Rule B: single `[{type:text,text:X}]` array → bare string `"X"`."""
    msg = {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    out = canonical_message(msg)
    assert out == {"role": "user", "content": "hi"}


def test_keeps_multi_block_arrays() -> None:
    """Rule B does NOT fire when the array has more than one block."""
    msg = {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "thinking..."},
            {"type": "tool_use", "id": "toolu_X", "name": "Read", "input": {}},
        ],
    }
    out = canonical_message(msg)
    # Content stays an array (no collapse).
    assert isinstance(out["content"], list)
    assert len(out["content"]) == 2


def test_keeps_array_when_single_text_has_extra_keys() -> None:
    """Edge case: single text block with cache_control. After Rule A
    drops cache_control the block has only {type,text}, so Rule B
    collapses. Documents the order-of-application.
    """
    msg = {
        "role": "user",
        "content": [{"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}],
    }
    out = canonical_message(msg)
    assert out == {"role": "user", "content": "x"}


def test_string_content_passthrough() -> None:
    """Bare-string content stays a bare string."""
    msg = {"role": "user", "content": "hi"}
    out = canonical_message(msg)
    assert out == {"role": "user", "content": "hi"}


def test_tool_use_block_id_preserved() -> None:
    """tool_use.id is verified-stable across rows; do not normalise."""
    msg = {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "I'll read the file."},
            {
                "type": "tool_use",
                "id": "toolu_01ABC",
                "name": "Read",
                "input": {"path": "/x"},
            },
        ],
    }
    out = canonical_message(msg)
    assert out["content"][1] == {
        "type": "tool_use",
        "id": "toolu_01ABC",
        "name": "Read",
        "input": {"path": "/x"},
    }


def test_tool_result_block_tool_use_id_preserved() -> None:
    """tool_result.tool_use_id is verified-stable across rows."""
    msg = {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_01ABC",
                "content": "file body",
            },
            {"type": "text", "text": "next?"},
        ],
    }
    out = canonical_message(msg)
    assert out["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "toolu_01ABC",
        "content": "file body",
    }


def test_thinking_signature_preserved() -> None:
    """Extended-thinking signature is verified-stable across rows."""
    msg = {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "ErcCClkIDR..."},
            {"type": "text", "text": "OK"},
        ],
    }
    out = canonical_message(msg)
    assert out["content"][0] == {
        "type": "thinking",
        "thinking": "",
        "signature": "ErcCClkIDR...",
    }
