"""Per-exchange classification for `plugin_analytics` rows.

ADR-0038 vocab. Three public entry points:

* `classify_request(request) -> Classification`
  Per-exchange classifier. Derives `slash_commands`, `first_msg_hash`,
  and `n_messages` from a parsed Anthropic Messages API request body.
  `first_msg_hash` powers the (B) chain-lookup that resolves
  `conversation_id`; `n_messages` is consumed in-flight only (not
  stored). The request-level `turn_kind` of ADR-0036 is retired.

* `classify_message(msg) -> MessageRole`
  Per-row role classifier. Operates on `messages[-1]` (the user-side
  delta of this exchange). Emits one of:
  - `user_input` — user's typed text (list with at least one
    non-wrapper text block).
  - `title_gen` — Claude Code's per-session title sidecar
    (`<session>...</session>` as a bare string or as a single bare
    text block).
  - `tool_result` — main-flow continuation (block list containing a
    `tool_result` block).
  - `sidecar` — every other framework-synthesised role=user payload:
    `/compact` summarize, `[SUGGESTION MODE: ...]`, step-away recap,
    post-`/compact` resume marker, list of only synthetic wrappers.

  `system_prompt` and `model_output` (ADR-0037) are not emitted:
  system data lives in its own column, model output in
  `response_jsonb` on the same row.

* `extract_request_content(msg) -> Any`
  Builds the `request_jsonb` value for the row. Drops synthetic
  wrapper blocks (`<system-reminder>`, `<command-*>`,
  `<local-command-*>`, post-`/compact` resume marker) from a list
  payload. If a single bare text block survives, collapses to a
  bare string. If only wrapper blocks exist (i.e. the row is a
  `sidecar` with no user text — e.g. the resume marker alone),
  returns the list verbatim so the original framing remains
  inspectable. String payloads are returned unchanged.

* `normalize_system(system_field) -> Any`
  Drops client-telemetry text blocks (`x-anthropic-billing-header:`
  prefix carrying `cc_version` / `cch` tokens that drift across
  exchanges) from the request's `system` field. Used by both the
  variation-tracking hash and the storage write so the invariant
  "same hash ⇒ identical stored bytes" holds.

`first_msg_hash` is SHA-256[:16] of the canonical user-typed text in
`messages[0]`. ADR-0036's (B) rule unchanged: same hash in the same
org collapses to the same `conversation_id`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Literal

# ADR-0038 per-row role vocab on `plugin_analytics.role`.
MessageRole = Literal[
    "user_input",
    "title_gen",
    "tool_result",
    "sidecar",
]

# Block-text prefixes Claude Code uses for synthesised content that
# wraps (but is not) user input. Shared between
# `_canonical_user_text` (for first_msg_hash) and
# `extract_request_content` (for request_jsonb stripping).
#
# Three categories:
#   1. Bracket-tag wrappers (`<system-reminder>`, `<command-*>`,
#      `<local-command-*>`) — Claude Code attaches these around or
#      alongside user-typed text in every main-flow message.
#   2. Post-/compact resume prose header.
#   3. Framework auto-call prompt prefixes — Claude Code internally
#      issues these LLM calls without a user typing them
#      (WebSearch trigger, PreCompact summarization request).
#      Listed as wrapper prefixes so the surrounding turn classifies
#      as `sidecar` (or stays `user_input` when accompanied by an
#      actual typed message), and the framework prompt itself does
#      not leak into `request_jsonb`. Whack-a-mole by design — new
#      framework prompts get added as discovered.
_SYNTHETIC_WRAPPER_PREFIXES: tuple[str, ...] = (
    "<system-reminder>",
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    # Post-/compact resume marker prose header.
    "This session is being continued",
    # Framework auto-call prompts (ADR-0038 refinement).
    "Perform a web search for the query: ",
    "CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.",
)

# Text-block prefixes Anthropic surfaces inside the system field for
# Claude Code client telemetry. The `cc_version` / `cch` tokens drift
# across exchanges without carrying any system-instruction content,
# so they get dropped before both the variation-tracking hash and
# the storage write.
_SYSTEM_METADATA_PREFIXES: tuple[str, ...] = ("x-anthropic-billing-header:",)

# Slash-command marker. Captures the bare command name (no leading slash).
_SLASH_RE = re.compile(r"<command-name>/([A-Za-z0-9_\-]+)</command-name>")

# `<session>\n…\n</session>` wrapper used by Claude Code's per-session
# title-gen sidecar. ADR-0036: stripping the wrapper inside
# `_canonical_user_text` lets the sidecar and the main-flow exchange
# share a `first_msg_hash`.
_SESSION_WRAP_RE = re.compile(r"^\s*<session>\s*(.*?)\s*</session>\s*$", re.DOTALL)


@dataclass(frozen=True)
class Classification:
    """Result of `classify_request`. Three independent fields."""

    slash_commands: list[str] | None  # None when no `<command-name>` blocks
    first_msg_hash: str
    n_messages: int


def classify_request(request: dict[str, Any]) -> Classification:
    """Classify a parsed Anthropic Messages API request body."""
    messages = request.get("messages") or []
    n = len(messages)
    first_msg_hash = _hash_first_message(messages[0]) if n > 0 else _hash_first_message({})

    if n == 0:
        return Classification(
            slash_commands=None,
            first_msg_hash=first_msg_hash,
            n_messages=0,
        )

    last_content = messages[-1].get("content") if isinstance(messages[-1], dict) else None
    slash_commands = (
        _extract_slash_commands(last_content) if isinstance(last_content, list) else None
    )
    return Classification(
        slash_commands=slash_commands,
        first_msg_hash=first_msg_hash,
        n_messages=n,
    )


def classify_message(msg: dict[str, Any]) -> MessageRole:
    """Classify a single user-side message (the exchange's `messages[-1]`).

    Returns one of `user_input`, `title_gen`, `tool_result`, `sidecar`
    per ADR-0038. The caller is responsible for invoking this only on
    the last message of a request; the Anthropic Messages API
    guarantees `messages[-1].role == "user"`.
    """
    content = msg.get("content")

    # title_gen: <session>...</session> as a bare string.
    if isinstance(content, str):
        if _SESSION_WRAP_RE.match(content):
            return "title_gen"
        # /compact summarize, [SUGGESTION MODE: …], step-away recap.
        return "sidecar"

    # title_gen, list form: single bare text block with the full
    # <session>...</session> payload. This is how Claude Code
    # delivers the sidecar over HTTP before Rule-B collapse used to
    # apply at storage time (now retired).
    if isinstance(content, list) and len(content) == 1:
        only = content[0]
        if (
            isinstance(only, dict)
            and _block_type(only) == "text"
            and _SESSION_WRAP_RE.match(only.get("text") or "")
        ):
            return "title_gen"

    # tool_result continuation: any tool_result block makes the
    # message a main-flow tool turn.
    if isinstance(content, list) and any(_block_type(b) == "tool_result" for b in content):
        return "tool_result"

    if not isinstance(content, list) or not content:
        return "sidecar"

    # user_input: at least one non-wrapper text block survives.
    if _last_real_user_text(content) is not None:
        return "user_input"

    # Only synthetic wrappers — sidecar (e.g. post-/compact resume marker).
    return "sidecar"


def extract_request_content(msg: dict[str, Any]) -> Any:
    """Compute the `request_jsonb` value for `messages[-1]`.

    Drops synthetic wrapper blocks from list content. If any
    non-wrapper blocks remain, returns just those (collapsing a
    single bare `{type:"text",text:"X"}` to the bare string `"X"`).
    If every block is a wrapper, returns the list verbatim so the
    sidecar payload (e.g. the post-`/compact` resume marker) stays
    inspectable. String content is returned unchanged.

    The wrapping `{role, content}` envelope is not produced — callers
    store only the inner content in `request_jsonb`. The row's
    `role` column carries the equivalent of the API role label.
    """
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list) or not content:
        return content

    stripped: list[Any] = []
    for b in content:
        if not isinstance(b, dict):
            stripped.append(b)
            continue
        if _block_type(b) != "text":
            stripped.append(b)
            continue
        text = (b.get("text") or "").lstrip()
        if text.startswith(_SYNTHETIC_WRAPPER_PREFIXES):
            continue
        stripped.append(b)

    if not stripped:
        # Wrapper-only payload. Preserve the original list — the row
        # classifies as `sidecar` and the wrappers are the only
        # information the row carries.
        return content

    # Rule-B collapse for the single-bare-text-block shape.
    if (
        len(stripped) == 1
        and isinstance(stripped[0], dict)
        and stripped[0].get("type") == "text"
        and set(stripped[0].keys()) == {"type", "text"}
    ):
        return stripped[0]["text"]
    return stripped


def normalize_system(system_field: Any) -> Any:
    """Drop client-telemetry blocks from a request's `system` field.

    Identifies text blocks whose `text` (after `lstrip`) starts with
    any `_SYSTEM_METADATA_PREFIXES` value and removes them. Shared
    by `_system_hash` (variation tracker) and `_resolve_system`
    (storage write) in the plugin module so the invariant
    "same hash ⇒ identical stored bytes" holds.

    Non-list inputs (str, None, anything else) pass through
    untouched — Claude Code sends the system field as a list of
    blocks; bare-string callers stay unchanged for safety.
    Non-dict / non-text list members also pass through.
    """
    if not isinstance(system_field, list):
        return system_field
    stripped: list[Any] = []
    for b in system_field:
        if isinstance(b, dict) and _block_type(b) == "text":
            text = (b.get("text") or "").lstrip()
            if text.startswith(_SYSTEM_METADATA_PREFIXES):
                continue
        stripped.append(b)
    return stripped


def _extract_slash_commands(content: list[Any]) -> list[str] | None:
    found: list[str] = []
    for b in content:
        if _block_type(b) != "text":
            continue
        text = b.get("text") or ""
        for match in _SLASH_RE.finditer(text):
            found.append(match.group(1))
    return found or None


def _hash_first_message(first: dict[str, Any]) -> str:
    """SHA-256[:16] of `messages[0]`'s canonical user-typed text."""
    canonical = _canonical_user_text(first.get("content"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _canonical_user_text(content: Any) -> str:
    """Extract the user-typed text from a message's `content`.

    String: strip a surrounding `<session>...</session>` wrapper if
    present, else return as-is.

    List: walk in reverse, skip blocks whose text starts with a
    synthetic-wrapper prefix, return the first remaining text block.
    Empty string if every text block is a wrapper or no text blocks
    exist.
    """
    if isinstance(content, str):
        m = _SESSION_WRAP_RE.match(content)
        return m.group(1) if m else content
    if isinstance(content, list):
        text = _last_real_user_text(content)
        return text if text is not None else ""
    return ""


def _last_real_user_text(content: list[Any]) -> str | None:
    for b in reversed(content):
        if _block_type(b) != "text":
            continue
        text = (b.get("text") or "").lstrip()
        if text.startswith(_SYNTHETIC_WRAPPER_PREFIXES):
            continue
        return text
    return None


def _block_type(block: Any) -> str | None:
    if not isinstance(block, dict):
        return None
    t = block.get("type")
    return t if isinstance(t, str) else None
