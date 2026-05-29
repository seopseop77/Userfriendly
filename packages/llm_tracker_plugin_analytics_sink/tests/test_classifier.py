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
    # ADR-0040: no user message carries text → None (was SHA-256("")).
    assert result.first_msg_hash is None
    assert result.slash_commands is None


def test_first_msg_hash_scans_past_wrapper_only_first_message() -> None:
    """ADR-0040: when `messages[0]` is wrapper-only (post-`/compact`
    resume marker), the hash keys on the first real user message, not
    the empty string."""
    marker = _user([{"type": "text", "text": "This session is being continued..."}])
    post_compact = classify_request(
        {
            "messages": [
                marker,
                {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
                _user([{"type": "text", "text": "강아지 좋아해?"}]),
            ]
        }
    )
    plain = classify_request({"messages": [_user([{"type": "text", "text": "강아지 좋아해?"}])]})
    assert post_compact.first_msg_hash == plain.first_msg_hash


def test_first_msg_hash_stable_across_post_compact_turns() -> None:
    """Successive post-`/compact` turns keep the resume marker at
    `messages[0]`; they must share one hash so they group together."""
    marker = _user([{"type": "text", "text": "This session is being continued..."}])
    assistant = {"role": "assistant", "content": [{"type": "text", "text": "..."}]}
    turn_a = classify_request({"messages": [marker, assistant, _user("강아지 좋아해?")]})
    turn_b = classify_request(
        {
            "messages": [
                marker,
                assistant,
                _user("강아지 좋아해?"),
                assistant,
                _user("강아지 vs 고양이"),
            ]
        }
    )
    assert turn_a.first_msg_hash == turn_b.first_msg_hash


def test_first_msg_hash_none_when_only_wrapper_messages() -> None:
    """Every user message wrapper-only → None (opens its own conv),
    not the shared empty-text hash."""
    result = classify_request(
        {"messages": [_user([{"type": "text", "text": "This session is being continued..."}])]}
    )
    assert result.first_msg_hash is None


def test_first_msg_hash_skips_assistant_text() -> None:
    """The scan considers only `role=user` messages — an assistant
    message must never become the conversation key."""
    result = classify_request(
        {
            "messages": [
                _user([{"type": "text", "text": "<system-reminder>\nx"}]),
                {"role": "assistant", "content": [{"type": "text", "text": "assistant text"}]},
                _user([{"type": "text", "text": "real question"}]),
            ]
        }
    )
    expected = classify_request({"messages": [_user("real question")]})
    assert result.first_msg_hash == expected.first_msg_hash


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


def test_classify_message_session_string_is_sidecar() -> None:
    """`<session>...</session>` title-generation sidecar arrives as
    a bare string; it folds into `sidecar` (2026-05-26 refinement —
    `title_gen` is no longer a separate role)."""
    msg = _user("<session>\n반가워!\n</session>")
    assert classify_message(msg) == "sidecar"


def test_classify_message_session_single_block_list_is_sidecar() -> None:
    """Regression: title-gen sidecar over HTTP — single-block list
    carrying the `<session>...</session>` payload — also classifies
    as sidecar."""
    msg = _user([{"type": "text", "text": "<session>\nhi\n</session>"}])
    assert classify_message(msg) == "sidecar"


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


def test_extract_strips_leading_wrappers() -> None:
    """Wrapper blocks are stripped; the surviving non-wrapper text
    is returned as a single-element list. Rule-B collapse to a
    bare string was removed 2026-05-26 for storage-shape
    uniformity."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nAvailable agent types..."},
            {"type": "text", "text": "<system-reminder>\nMCP Server..."},
            {"type": "text", "text": "hello"},
        ]
    )
    out = extract_request_content(msg)
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["text"] == "hello"


def test_extract_strips_command_wrappers_too() -> None:
    """`/clear` follow-up shape: `<command-name>` and
    `<local-command-stdout>` blocks count as wrappers, the trailing
    user text survives as the only non-wrapper block."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nAvailable agent types..."},
            {"type": "text", "text": "<command-name>/clear</command-name>"},
            {"type": "text", "text": "<local-command-stdout></local-command-stdout>"},
            {"type": "text", "text": "안녕~"},
        ]
    )
    out = extract_request_content(msg)
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["text"] == "안녕~"


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


def test_extract_single_block_bare_text_stays_array() -> None:
    """Rule-B collapse was removed 2026-05-26 — a single bare-text
    block is preserved as a one-element list, not collapsed to a
    bare string. Forward writes stay in array shape so downstream
    SQL never has to split on `jsonb_typeof`."""
    msg = _user([{"type": "text", "text": "first"}])
    out = extract_request_content(msg)
    assert isinstance(out, list)
    assert out == [{"type": "text", "text": "first"}]


def test_extract_single_block_with_cache_control_stays_array() -> None:
    """A bare text block with `cache_control` metadata is also
    returned as a list — same shape as the bare `{type, text}`
    case above. Forward writes are uniformly array-shaped."""
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
    assert isinstance(out, list)
    assert out[0]["text"] == "real"
    assert out[0]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------
# Framework auto-call prompts as wrappers (ADR-0038 refinement).
# ---------------------------------------------------------------------


def test_classify_websearch_trigger_is_sidecar() -> None:
    """Claude Code's internal WebSearch trigger appears as a user-role
    message whose only non-wrapper text starts with
    `"Perform a web search for the query: "`. After adding that
    prefix to the wrapper set, every text block is a wrapper → the
    payload is wrapper-only → the row classifies as sidecar."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nfoo"},
            {
                "type": "text",
                "text": "Perform a web search for the query: 오늘의 주요 뉴스 이슈",
            },
        ]
    )
    assert classify_message(msg) == "sidecar"


def test_classify_websearch_string_is_sidecar() -> None:
    """The WebSearch trigger also arrives as a bare string in some
    cases. The string-content branch of `classify_message` already
    returns sidecar — pinning the assertion here so a future
    string-path tweak does not silently regress."""
    msg = _user("Perform a web search for the query: 뉴스")
    assert classify_message(msg) == "sidecar"


def test_classify_precompact_prompt_is_sidecar() -> None:
    """The PreCompact auto-summarization prompt begins with
    `"CRITICAL: Respond with TEXT ONLY. Do NOT call any tools."`.
    On a turn where no real user input accompanies the framework
    prompt, every block is a wrapper and the row is sidecar."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nfoo"},
            {
                "type": "text",
                "text": (
                    "CRITICAL: Respond with TEXT ONLY. Do NOT call any tools."
                    "\n\nYour task is to create a detailed summary…"
                ),
            },
        ]
    )
    assert classify_message(msg) == "sidecar"


def test_classify_precompact_with_user_typed_is_user_input() -> None:
    """When PreCompact fires on a turn that also carries a user-typed
    block (or stdout that survived as non-wrapper), the trailing
    non-wrapper block remains and the row stays user_input. The
    framework prompt itself is stripped from `request_jsonb` because
    its prefix is in the wrapper set."""
    msg = _user(
        [
            {"type": "text", "text": "<command-name>/context</command-name>"},
            {"type": "text", "text": "## Context Usage\n…stdout"},
            {"type": "text", "text": "잘했으"},
            {
                "type": "text",
                "text": "CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.",
            },
        ]
    )
    assert classify_message(msg) == "user_input"
    out = extract_request_content(msg)
    # stdout + user typed survive; PreCompact prompt is stripped.
    assert isinstance(out, list)
    assert [b["text"] for b in out] == ["## Context Usage\n…stdout", "잘했으"]


def test_classify_webfetch_result_is_sidecar() -> None:
    """Claude Code surfaces a WebFetch tool's fetched page content as
    a user-role text block whose text starts with
    `"\\nWeb page content:\\n---\\n"` (the leading `\\n` is stripped
    by `lstrip` before the prefix check; the in-prefix `\\n---\\n` is
    the literal rule that separates the header from the page body).
    With the prefix in the wrapper set, a turn carrying only this
    block (plus `<system-reminder>` etc.) classifies as sidecar."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nfoo"},
            {
                "type": "text",
                "text": "\nWeb page content:\n---\n# Example page\n\nHello world…",
            },
        ]
    )
    assert classify_message(msg) == "sidecar"


def test_classify_webfetch_with_user_typed_is_user_input() -> None:
    """When a WebFetch result block sits alongside a user-typed block,
    the user-typed text survives and the row stays user_input. The
    fetched-content block is stripped from `request_jsonb`."""
    msg = _user(
        [
            {"type": "text", "text": "<system-reminder>\nfoo"},
            {"type": "text", "text": "내용 요약해줘"},
            {
                "type": "text",
                "text": "Web page content:\n---\n# Doc\n\nbody…",
            },
        ]
    )
    assert classify_message(msg) == "user_input"
    out = extract_request_content(msg)
    # User-typed block survives; WebFetch result is stripped.
    assert isinstance(out, list)
    assert [b["text"] for b in out] == ["내용 요약해줘"]


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
