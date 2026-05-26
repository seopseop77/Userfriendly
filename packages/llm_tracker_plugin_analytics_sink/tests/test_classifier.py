"""Unit tests for the ADR-0038 classifier.

Three surfaces:

* `classify_request` — first_msg_hash + slash_commands + n_messages.
  The ADR-0036 `turn_kind` output has been retired; per-row roles
  are now derived from `classify_message(messages[-1])` separately.
* `classify_message` — 4-value vocab (user_input / title_gen /
  tool_result / sidecar).
* `extract_request_content` — wrapper-stripping helper that builds
  the row's `request_jsonb` payload.
"""

from __future__ import annotations

from llm_tracker_plugin_analytics_sink.classifier import (
    Classification,
    classify_message,
    classify_request,
    extract_request_content,
    normalize_system,
)


def _user(content: object) -> dict:
    return {"role": "user", "content": content}


# ---------------------------------------------------------------------
# classify_request: hash + slash_commands + n_messages
# ---------------------------------------------------------------------


def test_first_msg_hash_stable_across_growth() -> None:
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


def test_first_msg_hash_differs_when_text_differs() -> None:
    a = classify_request({"messages": [_user([{"type": "text", "text": "hello"}])]})
    b = classify_request({"messages": [_user([{"type": "text", "text": "world"}])]})
    assert a.first_msg_hash != b.first_msg_hash


def test_first_msg_hash_string_and_single_block_collapse() -> None:
    """A bare string and a single-text-block list hash identically."""
    a = classify_request({"messages": [_user("hello")]})
    b = classify_request({"messages": [_user([{"type": "text", "text": "hello"}])]})
    assert a.first_msg_hash == b.first_msg_hash


def test_first_msg_hash_session_sidecar_matches_main_flow() -> None:
    """`<session>`-wrapped sidecar (string) and main flow (list with
    leading wrappers) share the same hash via canonical user text
    extraction. ADR-0036 (E)."""
    sidecar = classify_request({"messages": [_user("<session>\n반가워!\n</session>")]})
    main = classify_request(
        {
            "messages": [
                _user(
                    [
                        {"type": "text", "text": "<system-reminder>\nMCP..."},
                        {"type": "text", "text": "반가워!"},
                    ]
                )
            ]
        }
    )
    assert sidecar.first_msg_hash == main.first_msg_hash


def test_first_msg_hash_ignores_cache_control_metadata() -> None:
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
    assert result.slash_commands == ["clear"]


def test_slash_command_none_when_no_command_blocks() -> None:
    req = {"messages": [_user([{"type": "text", "text": "안녕"}])]}
    assert classify_request(req).slash_commands is None


def test_empty_messages_array_defensive() -> None:
    result = classify_request({"messages": []})
    assert result.n_messages == 0
    assert isinstance(result.first_msg_hash, str)
    assert len(result.first_msg_hash) == 16
    assert result.slash_commands is None


def test_classification_is_frozen_dataclass() -> None:
    import dataclasses

    result = classify_request({"messages": [_user("hi")]})
    assert isinstance(result, Classification)
    assert dataclasses.fields(Classification)
    try:
        result.first_msg_hash = "x" * 16  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Classification should be a frozen dataclass")


# ---------------------------------------------------------------------
# classify_message: ADR-0038 4-value role vocab.
# ---------------------------------------------------------------------


def test_classify_message_user_typed_list_is_user_input() -> None:
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nwrap"},
            {"type": "text", "text": "real text"},
        ]
    )
    assert classify_message(msg) == "user_input"


def test_classify_message_bare_string_user_text_is_sidecar() -> None:
    """A bare string is not classified as user_input — Claude Code's
    main-flow user messages always arrive as block lists. A bare
    string is a sub-prompt (SUGGESTION / /compact / step-away)."""
    assert classify_message(_user("[SUGGESTION MODE: ...]")) == "sidecar"
    assert classify_message(_user("CRITICAL: Respond with TEXT ONLY...")) == "sidecar"


def test_classify_message_session_string_is_title_gen() -> None:
    msg = _user("<session>\n반가워!\n</session>")
    assert classify_message(msg) == "title_gen"


def test_classify_message_session_single_block_list_is_title_gen() -> None:
    """Regression: title-gen sidecar over HTTP is a single-block list
    carrying the `<session>...</session>` payload."""
    msg = _user([{"type": "text", "text": "<session>\nhi\n</session>"}])
    assert classify_message(msg) == "title_gen"


def test_classify_message_tool_result_block_is_tool_result() -> None:
    msg = _user(
        [
            {"type": "tool_result", "tool_use_id": "t", "content": "ok"},
        ]
    )
    assert classify_message(msg) == "tool_result"


def test_classify_message_tool_result_alongside_wrappers_is_tool_result() -> None:
    """A tool_result block makes the whole message a tool turn even
    when post-tool hook wrappers are appended."""
    msg = _user(
        [
            {"type": "tool_result", "tool_use_id": "t", "content": "ok"},
            {"type": "text", "text": "<system-reminder>\nposttool"},
        ]
    )
    assert classify_message(msg) == "tool_result"


def test_classify_message_only_wrappers_is_sidecar() -> None:
    """The post-`/compact` resume marker shape — only synthetic
    wrapper blocks, no real user text."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nNote..."},
            {"type": "text", "text": "This session is being continued..."},
        ]
    )
    assert classify_message(msg) == "sidecar"


def test_classify_message_empty_content_defensive() -> None:
    assert classify_message(_user([])) == "sidecar"
    assert classify_message(_user(None)) == "sidecar"


def test_classify_message_session_in_multi_block_list_is_user_input() -> None:
    """`<session>` text inside a multi-block list (alongside other
    user content) is treated as the user's typed text, not a
    title-gen sidecar. title_gen requires the entire message body
    to be the `<session>...</session>` payload."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nfoo"},
            {"type": "text", "text": "<session>\nreal user input\n</session>"},
        ]
    )
    assert classify_message(msg) == "user_input"


# ---------------------------------------------------------------------
# extract_request_content: wrapper stripping + Rule B.
# ---------------------------------------------------------------------


def test_extract_strips_leading_wrappers_and_collapses_single_block() -> None:
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nAvailable agent types..."},
            {"type": "text", "text": "<system-reminder>\nMCP Server..."},
            {"type": "text", "text": "hello"},
        ]
    )
    assert extract_request_content(msg) == "hello"


def test_extract_strips_command_wrappers_too() -> None:
    """`/clear` follow-up shape: `<command-name>` and
    `<local-command-stdout>` blocks count as wrappers, the trailing
    user text survives."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nAvailable agent types..."},
            {"type": "text", "text": "<command-name>/clear</command-name>"},
            {"type": "text", "text": "<local-command-stdout></local-command-stdout>"},
            {"type": "text", "text": "안녕~"},
        ]
    )
    assert extract_request_content(msg) == "안녕~"


def test_extract_returns_list_when_multiple_non_wrapper_blocks() -> None:
    """Multiple non-wrapper blocks remain — no Rule B collapse."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nfoo"},
            {"type": "text", "text": "first user line"},
            {"type": "text", "text": "second user line"},
        ]
    )
    out = extract_request_content(msg)
    assert isinstance(out, list)
    assert [b["text"] for b in out] == ["first user line", "second user line"]


def test_extract_preserves_wrapper_only_payload_as_list() -> None:
    """If every block is a wrapper, return the original list so the
    sidecar payload (e.g. post-/compact resume marker) stays
    inspectable."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nNote: STATUS.md was read"},
            {"type": "text", "text": "This session is being continued..."},
        ]
    )
    out = extract_request_content(msg)
    assert isinstance(out, list)
    assert len(out) == 2
    assert out[0]["text"].startswith("<system-reminder>")


def test_extract_string_content_returned_verbatim() -> None:
    assert extract_request_content(_user("<session>\nfoo\n</session>")) == (
        "<session>\nfoo\n</session>"
    )
    assert extract_request_content(_user("[SUGGESTION MODE: ...]")) == "[SUGGESTION MODE: ...]"


def test_extract_tool_result_blocks_returned_verbatim() -> None:
    """tool_result blocks aren't wrappers — return the list as-is."""
    blocks = [{"type": "tool_result", "tool_use_id": "t", "content": "x"}]
    msg = _user(blocks)
    out = extract_request_content(msg)
    assert out == blocks


def test_extract_single_block_bare_text_collapses_to_string() -> None:
    """Rule B: a list with one bare text block collapses to a string."""
    msg = _user([{"type": "text", "text": "first"}])
    assert extract_request_content(msg) == "first"


def test_extract_drops_cache_control_keys() -> None:
    """A bare text block with `cache_control` metadata does NOT have
    `{type, text}` as its only keys, so Rule B does not collapse it
    — extracted as a list. (Future tightening could strip
    cache_control here; for now the test pins current behaviour.)"""
    msg = _user(
        [
            {
                "type": "text",
                "text": "real",
                "cache_control": {"type": "ephemeral"},
            }
        ]
    )
    out = extract_request_content(msg)
    # Returned as a list since the block doesn't match the bare
    # `{type, text}` shape required for Rule B collapse.
    assert isinstance(out, list)
    assert out[0]["text"] == "real"


# ---------------------------------------------------------------------
# normalize_system: drop `x-anthropic-billing-header` telemetry blocks.
# ---------------------------------------------------------------------


def test_normalize_system_strips_billing_header_block() -> None:
    sf = [
        {
            "type": "text",
            "text": "x-anthropic-billing-header: cc_version=2.1.150; cc_entrypoint=cli; cch=f5075;",
        },
        {"type": "text", "text": "You are Claude Code..."},
    ]
    assert normalize_system(sf) == [{"type": "text", "text": "You are Claude Code..."}]


def test_normalize_system_preserves_blocks_without_metadata_prefix() -> None:
    sf = [
        {"type": "text", "text": "You are Claude Code..."},
        {"type": "text", "text": "Some other instruction"},
    ]
    assert normalize_system(sf) == sf


def test_normalize_system_billing_header_only_returns_empty_list() -> None:
    sf = [{"type": "text", "text": "x-anthropic-billing-header: cc_version=2.1;"}]
    assert normalize_system(sf) == []


def test_normalize_system_string_passes_through() -> None:
    """Claude Code sends system as a list of blocks, but the helper
    is defensive — bare strings pass through untouched."""
    assert normalize_system("be brief") == "be brief"


def test_normalize_system_none_passes_through() -> None:
    assert normalize_system(None) is None


def test_normalize_system_preserves_cache_control_keys_on_kept_blocks() -> None:
    """`cache_control` metadata on a kept block survives normalization;
    it's stripped only inside `_system_hash` (text-only extraction)."""
    sf = [
        {
            "type": "text",
            "text": "You are Claude Code...",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    out = normalize_system(sf)
    assert out == sf


def test_normalize_system_idempotent() -> None:
    """Running normalize_system twice returns the same value as
    once. Required for the variation-tracker invariant: re-hashing a
    previously-stored (already-normalized) system must produce the
    same hash as hashing the freshly-normalized current system."""
    sf = [
        {"type": "text", "text": "x-anthropic-billing-header: cc_version=2.1;"},
        {"type": "text", "text": "You are Claude Code..."},
    ]
    once = normalize_system(sf)
    twice = normalize_system(once)
    assert once == twice
