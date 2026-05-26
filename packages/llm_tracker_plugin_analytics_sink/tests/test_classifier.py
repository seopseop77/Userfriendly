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
    classify_message,
    classify_request,
    split_first_message,
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
    """No Claude Code system + `<session>` wrapper = real claude-manage probe."""
    req = {
        "messages": [_user([{"type": "text", "text": "<session>\nSTATUS.md 읽어봐\n</session>"}])]
    }
    result = classify_request(req)
    assert result.turn_kind == "claude_manage_probe"


def test_title_generation_call_is_internal_subprompt() -> None:
    """Claude Code's per-session title fetch carries the user's first
    message inside a small request gated by a distinctive system prompt.
    Even with a `<session>` user wrapper, the system signature wins —
    this is not a real user turn.
    """
    req = {
        "system": [
            {"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude."},
            {
                "type": "text",
                "text": (
                    "Generate a concise, sentence-case title (3-7 words) "
                    "that captures the main topic or goal of this coding session."
                ),
            },
        ],
        "messages": [
            _user(
                [
                    {
                        "type": "text",
                        "text": "<session>\nRLS가 뭔지 자세하게 설명해봐\n</session>",
                    }
                ]
            )
        ],
    }
    result = classify_request(req)
    assert result.turn_kind == "internal_subprompt"


def test_claude_code_with_session_wrapper_is_real_user_turn() -> None:
    """If Claude Code is the originator (system signature present) and
    `<session>` is just the user's wrapper around their typed text, the
    last text block being `<session>...` no longer marks it as a probe —
    it's a real user turn.
    """
    req = {
        "system": "You are Claude Code, Anthropic's official CLI for Claude.",
        "messages": [
            _user(
                [
                    {"type": "text", "text": "<system-reminder>\nAvailable agent types..."},
                    {"type": "text", "text": "<session>\n반가워\n</session>"},
                ]
            )
        ],
    }
    result = classify_request(req)
    assert result.turn_kind == "user_input_turn_start"


def test_step_away_recap_is_internal_subprompt() -> None:
    """Claude Code's `The user stepped away` recap arrives as
    string-shaped content; the content=string rule catches it.
    """
    req = {
        "messages": [
            _user("hello"),
            _asst_tool_use(),
            _user(
                "The user stepped away and is coming back. "
                "Recap in under 40 words, 1-2 plain sentences, no markdown."
            ),
        ]
    }
    result = classify_request(req)
    assert result.turn_kind == "internal_subprompt"


def test_title_generation_system_field_string_form() -> None:
    """The `system` field may be a single string instead of a block list."""
    req = {
        "system": (
            "You are Claude Code, Anthropic's official CLI for Claude.\n"
            "Generate a concise, sentence-case title (3-7 words)."
        ),
        "messages": [_user([{"type": "text", "text": "<session>\nSTATUS.md 읽어봐\n</session>"}])],
    }
    result = classify_request(req)
    assert result.turn_kind == "internal_subprompt"


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


# ---------------------------------------------------------------------
# ADR-0036: canonical user-text hash + per-message classifier.
# ---------------------------------------------------------------------


def test_first_msg_hash_session_sidecar_matches_main_flow() -> None:
    """The `<session>`-wrapped sidecar (string content) and the main
    flow (list content with leading wrappers) share the same hash
    when their underlying user-typed text matches. ADR-0036 (E).
    """
    session_sidecar = classify_request(
        {"messages": [_user("<session>\n너무 반가워! 잘 지냈어?\n</session>")]}
    )
    main_flow = classify_request(
        {
            "messages": [
                _user(
                    [
                        {"type": "text", "text": "<system-reminder>\nMCP Server..."},
                        {"type": "text", "text": "<system-reminder>\nSession-specific..."},
                        {"type": "text", "text": "너무 반가워! 잘 지냈어?"},
                    ]
                )
            ]
        }
    )
    assert session_sidecar.first_msg_hash == main_flow.first_msg_hash


def test_first_msg_hash_skips_synthetic_wrapper_blocks() -> None:
    """Adding/removing leading `<system-reminder>` blocks does not
    change the hash because they are skipped during canonicalisation.
    """
    with_wrapper = classify_request(
        {
            "messages": [
                _user(
                    [
                        {"type": "text", "text": "<system-reminder>\nfoo"},
                        {
                            "type": "text",
                            "text": "<local-command-stdout>bar</local-command-stdout>",
                        },
                        {"type": "text", "text": "real input"},
                    ]
                )
            ]
        }
    )
    without_wrapper = classify_request(
        {"messages": [_user([{"type": "text", "text": "real input"}])]}
    )
    assert with_wrapper.first_msg_hash == without_wrapper.first_msg_hash


def test_first_msg_hash_only_wrappers_collapses_to_empty() -> None:
    """A `messages[0]` with only synthetic wrappers (no user text)
    hashes the empty string. Two such messages share a hash —
    acceptable per the (B) trade-off; production rarely emits this
    shape outside the post-`/compact` resume marker case.
    """
    a = classify_request(
        {"messages": [_user([{"type": "text", "text": "<system-reminder>\nfoo"}])]}
    )
    b = classify_request(
        {"messages": [_user([{"type": "text", "text": "This session is being continued..."}])]}
    )
    assert a.first_msg_hash == b.first_msg_hash


# ---------------------------------------------------------------------
# ADR-0037: 5-role display vocab on conversation_messages.role.
# `classify_message` now emits system_prompt / user_input / title_gen /
# model_output / assistant. (system_prompt is only assigned by the
# splitter; the per-message classifier never returns it directly.)
# ---------------------------------------------------------------------


def test_classify_message_assistant_role_is_model_output() -> None:
    msg = {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}
    assert classify_message(msg) == "model_output"


def test_classify_message_user_typed_list_content_is_user_input() -> None:
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nwrap"},
            {"type": "text", "text": "real text"},
        ]
    )
    assert classify_message(msg) == "user_input"


def test_classify_message_tool_result_continuation_is_assistant() -> None:
    """tool_result continuations fold into the `assistant` bucket
    under ADR-0037 (operator direction: continuations and non-title-gen
    sub-prompts share one display role)."""
    msg = _user(
        [
            {"type": "tool_result", "tool_use_id": "t", "content": "ok"},
            {"type": "text", "text": "<system-reminder>\nposttool"},
        ]
    )
    assert classify_message(msg) == "assistant"


def test_classify_message_non_session_string_is_assistant() -> None:
    """`/compact` summarize, SUGGESTION MODE, step-away recap —
    all framework-generated string sub-prompts fold into `assistant`."""
    assert classify_message(_user("[SUGGESTION MODE: ...]")) == "assistant"
    assert classify_message(_user("CRITICAL: Respond with TEXT ONLY...")) == "assistant"


def test_classify_message_session_string_is_title_gen() -> None:
    """The `<session>`-wrapped string is Claude Code's per-session
    title fetch — split out from `assistant` under ADR-0037."""
    msg = _user("<session>\n너무 반가워!\n</session>")
    assert classify_message(msg) == "title_gen"


def test_classify_message_only_synthetic_wrappers_is_assistant() -> None:
    """A user message whose only text blocks are synthetic wrappers
    (e.g. the post-`/compact` resume marker without trailing user
    input) is not user input — folds into `assistant`."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nNote: STATUS.md was read"},
            {"type": "text", "text": "This session is being continued..."},
        ]
    )
    assert classify_message(msg) == "assistant"


def test_classify_message_empty_content_defensive() -> None:
    assert classify_message(_user([])) == "assistant"
    assert classify_message(_user(None)) == "assistant"


def test_classify_message_session_wrap_on_list_is_user_input() -> None:
    """`<session>` inside a *multi-block* list (alongside wrappers and
    other user text) is not title_gen — title_gen detection requires
    that the entire message body be the `<session>...</session>`
    payload. Multi-block list with `<session>` as one of several
    blocks classifies as user_input."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nfoo"},
            {"type": "text", "text": "<session>\n반가워\n</session>"},
        ]
    )
    assert classify_message(msg) == "user_input"


def test_classify_message_session_wrap_single_block_list_is_title_gen() -> None:
    """Claude Code's title-gen sidecar arrives over HTTP with
    `messages[0].content` as a single bare text block carrying the
    full `<session>...</session>` payload. The Rule B normaliser later
    collapses it to a bare string, but `classify_message` runs on the
    un-normalised dict — so the list-of-one shape must also match
    title_gen, not user_input. (Regression: conv 01KSGW0CHY3HAFEM4QRRJ3Y1ST,
    2026-05-26.)"""
    msg = _user([{"type": "text", "text": "<session>\n안녕! 너를 소개해봐\n</session>"}])
    assert classify_message(msg) == "title_gen"


def test_classify_message_single_block_non_session_is_user_input() -> None:
    """A single bare text block whose content is plain user input (not
    a `<session>` wrapper) must still classify as user_input — the new
    list-of-one title_gen branch is gated on the full session shape."""
    msg = _user([{"type": "text", "text": "안녕"}])
    assert classify_message(msg) == "user_input"


# ---------------------------------------------------------------------
# split_first_message — peels leading synthetic wrappers from
# messages[0] into a system_prompt slice and a user_input slice.
# ---------------------------------------------------------------------


def test_split_first_message_session_opener_shape() -> None:
    """The canonical Claude Code session opener: one or more wrapper
    blocks followed by the user's typed text. Splits into two rows."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nAvailable agent types..."},
            {"type": "text", "text": "<system-reminder>\nMCP Server Instructions..."},
            {"type": "text", "text": "STATUS.md 읽어줘"},
        ]
    )
    result = split_first_message(msg)
    assert result is not None
    system_blocks, user_msg = result
    assert len(system_blocks) == 2
    assert all(b["text"].startswith("<system-reminder>") for b in system_blocks)
    assert user_msg["role"] == "user"
    assert user_msg["content"] == [{"type": "text", "text": "STATUS.md 읽어줘"}]


def test_split_first_message_no_wrapper_returns_none() -> None:
    """Single user-typed block at index 0 — nothing to peel."""
    msg = _user([{"type": "text", "text": "quota"}])
    assert split_first_message(msg) is None


def test_split_first_message_string_content_returns_none() -> None:
    """String content (title_gen sidecar, /compact, SUGGESTION MODE,
    etc.) is not a candidate for splitting."""
    assert split_first_message(_user("<session>\nfoo\n</session>")) is None
    assert split_first_message(_user("[SUGGESTION MODE: ...]")) is None


def test_split_first_message_only_wrappers_returns_none() -> None:
    """Every block is a wrapper — no real user text to peel off,
    so no split. The whole message classifies as `assistant` later."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nNote: STATUS.md was read"},
            {"type": "text", "text": "This session is being continued..."},
        ]
    )
    assert split_first_message(msg) is None


def test_split_first_message_assistant_role_returns_none() -> None:
    """Assistant messages never carry wrapper-prefixed user input."""
    msg = {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "<system-reminder>\nfoo"},
            {"type": "text", "text": "ok"},
        ],
    }
    assert split_first_message(msg) is None


def test_split_first_message_slash_command_block_kept_with_user() -> None:
    """`<command-name>` blocks are wrappers; the user's follow-up text
    after a /clear or /compact still peels into user_input."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nAvailable agent types..."},
            {"type": "text", "text": "<command-name>/clear</command-name>"},
            {"type": "text", "text": "<local-command-stdout></local-command-stdout>"},
            {"type": "text", "text": "안녕~"},
        ]
    )
    result = split_first_message(msg)
    assert result is not None
    system_blocks, user_msg = result
    assert len(system_blocks) == 3
    assert user_msg["content"] == [{"type": "text", "text": "안녕~"}]
