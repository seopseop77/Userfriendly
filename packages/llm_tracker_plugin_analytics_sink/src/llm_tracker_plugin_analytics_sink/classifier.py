"""Turn classification for `plugin_analytics` rows.

Pure functions — no I/O, no DB. The plugin's `on_persisted` calls
`classify_request(...)` to derive the four content-derived fields
(`turn_kind`, `slash_commands`, `first_msg_hash`, plus `n_messages`
which the caller uses for the chain-lookup that resolves
`conversation_id`). All rules are documented in
`docs/worklog/2026-05-19-turn-classification.md`.

Rule summary (see worklog for derivation):

1. `messages[-1].role` is always `"user"` per Anthropic Messages API.
2. If `content` is a string (not an array of blocks), the request is
   an internal sub-prompt that Claude Code generated rather than a
   user-typed turn — e.g. the `/compact` summarize call or the
   `[SUGGESTION MODE: ...]` autocomplete probe.
3. If any block in `content` is a `tool_result`, this request is a
   continuation of a turn already in flight.
4. The `<session>...</session>` wrapper signature on a small,
   `cc_version`-tagged request identifies `claude-manage` probes
   that ride the same proxy. Detected on the last text block.
5. Otherwise, walking the content array from the end and skipping
   Claude Code's synthesised wrapper blocks (`<system-reminder>`,
   `<local-command-*>`, `<command-*>`, post-compact resume marker),
   the first remaining text block is what the user actually typed
   — `user_input_turn_start`.

Slash command extraction scans the content array for
`<command-name>/foo</command-name>` markers. /clear, /compact, and
custom skills all surface this way.

`first_msg_hash` is SHA-256[:16] of the canonical text of
`messages[0]`. `cache_control` and other metadata fields are
deliberately excluded so prompt-caching toggles do not invalidate
identity.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Literal

TurnKind = Literal[
    "user_input_turn_start",
    "tool_continuation",
    "internal_subprompt",
    "claude_manage_probe",
]

# Block text prefixes Claude Code uses for synthesised content that wraps
# (but is not) user input. Order matters only for documentation.
_SYNTHETIC_WRAPPER_PREFIXES: tuple[str, ...] = (
    "<system-reminder>",
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    # The post-/compact resume conversation seeds messages[0] with a
    # block that starts with this prose summary header.
    "This session is being continued",
)

# Matches Claude Code's slash-command marker, e.g.
#   <command-name>/clear</command-name>
# Captures the bare command name (without the leading slash).
_SLASH_RE = re.compile(r"<command-name>/([A-Za-z0-9_\-]+)</command-name>")


@dataclass(frozen=True)
class Classification:
    """Result of `classify_request`. All four fields are independent."""

    turn_kind: TurnKind
    slash_commands: list[str] | None  # None when no <command-name> blocks present
    first_msg_hash: str
    n_messages: int


def classify_request(request: dict[str, Any]) -> Classification:
    """Classify a parsed Anthropic Messages API request body."""
    messages = request.get("messages") or []
    n = len(messages)
    first_msg_hash = _hash_first_message(messages[0]) if n > 0 else _hash_first_message({})

    if n == 0:
        # Defensive: no messages at all. Treat as internal — the API
        # would reject it but we still want a deterministic label.
        return Classification(
            turn_kind="internal_subprompt",
            slash_commands=None,
            first_msg_hash=first_msg_hash,
            n_messages=0,
        )

    last = messages[-1]
    content = last.get("content")
    slash_commands = _extract_slash_commands(content) if isinstance(content, list) else None
    turn_kind = _classify_kind(content)

    return Classification(
        turn_kind=turn_kind,
        slash_commands=slash_commands,
        first_msg_hash=first_msg_hash,
        n_messages=n,
    )


def _classify_kind(content: Any) -> TurnKind:
    # Rule 2: string content = Claude Code internal sub-prompt.
    if isinstance(content, str):
        return "internal_subprompt"

    if not isinstance(content, list) or not content:
        # No content blocks: treat as continuation (impossible-shape).
        return "tool_continuation"

    # Rule 3: tool_result anywhere in the array = mid-turn continuation.
    if any(_block_type(b) == "tool_result" for b in content):
        return "tool_continuation"

    # Find the last text block — it's where the user's typed text lives
    # (or where the claude-manage `<session>` wrapper lives, or a
    # synthesised wrapper if no real user text is present).
    last_text: str | None = None
    for b in reversed(content):
        if _block_type(b) == "text":
            last_text = (b.get("text") or "").lstrip()
            break

    if last_text is None:
        return "tool_continuation"

    # Rule 4: claude-manage signature.
    if last_text.startswith("<session>"):
        return "claude_manage_probe"

    # Rule 5: walk blocks from end, skip synthesised wrappers; first
    # remaining text block = real user input.
    for b in reversed(content):
        if _block_type(b) != "text":
            continue
        text = (b.get("text") or "").lstrip()
        if text.startswith(_SYNTHETIC_WRAPPER_PREFIXES):
            continue
        return "user_input_turn_start"

    # Only synthesised wrappers — no real user text. Treat as
    # continuation (e.g. tool_result-less injected reminder).
    return "tool_continuation"


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
    """SHA-256[:16] of `messages[0]`'s canonical text."""
    content = first.get("content")
    if isinstance(content, str):
        canonical = content
    elif isinstance(content, list):
        canonical = "\n".join((b.get("text") or "") for b in content if _block_type(b) == "text")
    else:
        canonical = ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _block_type(block: Any) -> str | None:
    if not isinstance(block, dict):
        return None
    t = block.get("type")
    return t if isinstance(t, str) else None
