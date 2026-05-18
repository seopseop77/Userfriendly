"""Unit tests for the turn classifier.

The shapes covered here were derived from real `plugin_analytics`
rows captured in the 5/19 KST session (see
`docs/worklog/2026-05-19-turn-classification.md`):

* user-typed fresh prompt (session resume with wrapper blocks)
* mid-conversation user follow-up (single text block)
* tool-result continuation (text + tool_result blocks)
* `/compact` internal summarize call (content = string)
* `[SUGGESTION MODE: ...]` autocomplete probe (content = string)
* claude-manage probe (`<session>...</session>` wrapper, small body)
* /clear and /compact slash-command extraction from block array
* identical first-message hashing stability
"""

from __future__ import annotations

from llm_tracker_plugin_analytics_sink.classifier import (
    Classification,
    classify_request,
)


def _user(content: object) -> dict:
    return {"role": "user", "content": content}


def _asst_tool_use():
    return {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "ok"},
            {"type": "tool_use", "id": "toolu_01", "name": "LS", "input": {}},
        ],
    }


def test_session_resume_user_input_turn_start() -> None:
    """First request of a Claude Code session: wrappers + final user text."""
    req = {
        "messages": [
            _user(
                [
                    {"type": "text", "text": "<system-reminder>\nAvailable agent types..."},
                    {"type": "text", "text": "<system-reminder>\nMCP Server Instructions..."},
                    {"type": "text", "text": "Status.md 읽고 next single step 알려줘"},
                ]
            )
        ]
    }
    result = classify_request(req)
    assert result.turn_kind == "user_input_turn_start"
    assert result.slash_commands is None
    assert result.n_messages == 1


def test_mid_conversation_user_followup() -> None:
    """User types a follow-up after assistant ended with end_turn."""
    req = {
        "messages": [
            _user("first"),
            _asst_tool_use(),
            _user([{"type": "tool_result", "tool_use_id": "toolu_01", "content": "x"}]),
            {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            _user([{"type": "text", "text": "이미 fly deploy는 끝낸 상태야."}]),
        ]
    }
    result = classify_request(req)
    assert result.turn_kind == "user_input_turn_start"
    assert result.n_messages == 5


def test_tool_result_continuation() -> None:
    """Last user block contains tool_result → same-turn continuation."""
    req = {
        "messages": [
            _user("first"),
            _asst_tool_use(),
            _user(
                [
                    {"type": "tool_result", "tool_use_id": "toolu_01", "content": "ok"},
                    {"type": "text", "text": "<system-reminder>\nPostToolUse:Read hook..."},
                ]
            ),
        ]
    }
    result = classify_request(req)
    assert result.turn_kind == "tool_continuation"
    assert result.n_messages == 3


def test_compact_summarize_internal_subprompt() -> None:
    """`/compact` summarize call: content is a raw string, not a block list."""
    req = {
        "messages": [
            _user("first"),
            _asst_tool_use(),
            _user(
                "CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.\n"
                "- Your job is to summarise the conversation above..."
            ),
        ]
    }
    result = classify_request(req)
    assert result.turn_kind == "internal_subprompt"
    assert result.slash_commands is None


def test_suggestion_mode_internal_subprompt() -> None:
    req = {
        "messages": [
            _user("seed"),
            _user(
                "[SUGGESTION MODE: Suggest what the user might naturally type "
                "next into Claude Code.]"
            ),
        ]
    }
    result = classify_request(req)
    assert result.turn_kind == "internal_subprompt"


def test_claude_manage_probe_detected() -> None:
    req = {
        "messages": [_user([{"type": "text", "text": "<session>\nSTATUS.md 읽어봐\n</session>"}])]
    }
    result = classify_request(req)
    assert result.turn_kind == "claude_manage_probe"


def test_slash_command_clear_extracted() -> None:
    req = {
        "messages": [
            _user(
                [
                    {"type": "text", "text": "<system-reminder>\nAvailable agent types..."},
                    {"type": "text", "text": "<local-command-caveat>Caveat..."},
                    {
                        "type": "text",
                        "text": (
                            "<command-name>/clear</command-name>\n"
                            "<command-message>clear</command-message>"
                        ),
                    },
                    {"type": "text", "text": "<local-command-stdout></local-command-stdout>"},
                    {"type": "text", "text": "안녕~"},
                ]
            )
        ]
    }
    result = classify_request(req)
    assert result.turn_kind == "user_input_turn_start"
    assert result.slash_commands == ["clear"]


def test_slash_command_compact_followup_extracted() -> None:
    req = {
        "messages": [
            _user(
                [
                    {"type": "text", "text": "<system-reminder>\nAvailable agent types..."},
                    {"type": "text", "text": "This session is being continued from a previous..."},
                    {"type": "text", "text": "<command-name>/compact</command-name>"},
                    {
                        "type": "text",
                        "text": "<local-command-stdout>Compacted</local-command-stdout>",
                    },
                    {"type": "text", "text": "반가워. 다시 시작하자."},
                ]
            )
        ]
    }
    result = classify_request(req)
    assert result.turn_kind == "user_input_turn_start"
    assert result.slash_commands == ["compact"]


def test_post_compact_resume_marker_skipped() -> None:
    """A messages[0] whose only content is the resume marker + wrappers
    (no user text yet) is treated as tool_continuation, not user input.
    """
    req = {
        "messages": [
            _user(
                [
                    {"type": "text", "text": "<system-reminder>\nNote: STATUS.md was read..."},
                    {"type": "text", "text": "This session is being continued from a previous..."},
                ]
            )
        ]
    }
    result = classify_request(req)
    assert result.turn_kind == "tool_continuation"


def test_first_msg_hash_stable_across_growth() -> None:
    """Adding more turns to messages[] does not change first_msg_hash."""
    base_first = _user([{"type": "text", "text": "hello"}])
    short = classify_request({"messages": [base_first]})
    long_ = classify_request(
        {
            "messages": [
                base_first,
                {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
                _user([{"type": "text", "text": "follow-up"}]),
            ]
        }
    )
    assert short.first_msg_hash == long_.first_msg_hash


def test_first_msg_hash_ignores_cache_control_metadata() -> None:
    """cache_control siblings on a text block don't change the hash."""
    a = classify_request({"messages": [_user([{"type": "text", "text": "hello"}])]})
    b = classify_request(
        {
            "messages": [
                _user(
                    [
                        {
                            "type": "text",
                            "text": "hello",
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                )
            ]
        }
    )
    assert a.first_msg_hash == b.first_msg_hash


def test_first_msg_hash_differs_when_text_differs() -> None:
    a = classify_request({"messages": [_user([{"type": "text", "text": "hello"}])]})
    b = classify_request({"messages": [_user([{"type": "text", "text": "world"}])]})
    assert a.first_msg_hash != b.first_msg_hash


def test_string_content_hashed_consistently() -> None:
    """messages[0] with string content hashes identically to a single text block."""
    a = classify_request({"messages": [_user("hello")]})
    b = classify_request({"messages": [_user([{"type": "text", "text": "hello"}])]})
    assert a.first_msg_hash == b.first_msg_hash


def test_empty_messages_array_defensive() -> None:
    """Defensive: zero-length messages → internal_subprompt, deterministic."""
    result = classify_request({"messages": []})
    assert result.turn_kind == "internal_subprompt"
    assert result.n_messages == 0
    assert isinstance(result.first_msg_hash, str)
    assert len(result.first_msg_hash) == 16


def test_classification_is_frozen_dataclass() -> None:
    """Callers should not mutate classification results."""
    result = classify_request({"messages": [_user("hi")]})
    assert isinstance(result, Classification)
    import dataclasses

    assert dataclasses.fields(Classification)  # has fields
    # frozen=True is the contract
    try:
        result.turn_kind = "tool_continuation"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Classification should be a frozen dataclass")
