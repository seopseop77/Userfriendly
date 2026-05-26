"""Turn classification for `plugin_analytics` rows.

Pure functions — no I/O, no DB. Three public entry points:

* `classify_request(...)` — per-exchange classifier. Derives
  `turn_kind`, `slash_commands`, `first_msg_hash`, `n_messages` from
  the parsed Anthropic Messages API request body. The plugin uses
  the result for the analytics row and the chain-lookup that
  resolves `conversation_id`.
* `classify_message(msg) -> MessageRole` — per-message classifier.
  Returns the *display role* of an individual message for the
  `conversation_messages.role` column (ADR-0037). Five-value vocab:
  `system_prompt`, `user_input`, `title_gen`, `model_output`,
  `assistant`. `system_prompt` is never emitted from
  `classify_message` directly — it is only assigned by the splitter
  on `messages[0]` (see `split_first_message`).
* `split_first_message(msg)` — splits a `messages[0]` whose content
  array begins with synthetic wrapper blocks (`<system-reminder>`,
  `<command-name>`, …) into a `(system_prompt_blocks, user_input_msg)`
  pair so each lands in its own `conversation_messages` row.
  Returns `None` when no split applies.

`TurnKind` (the request-level vocab written to
`plugin_analytics.turn_kind`) is unchanged from ADR-0036 — the
classifier still emits the original four values. The display vocab
for `conversation_messages.role` diverged from `TurnKind` under
ADR-0037; downstream queries that joined `cm.role = pa.turn_kind`
must update.

`classify_request` rule summary (see worklog
`2026-05-19-turn-classification.md` for derivation; per-message
classifier mirrors rules 3, 4, and 6 since system_text is not
available at the per-message scope):

1. `messages[-1].role` is always `"user"` per Anthropic Messages API.
2. If the `system` field contains Claude Code's title-generation
   signature ("Generate a concise, sentence-case title"), this is
   Claude Code's per-session title fetch, not a user-typed turn —
   `internal_subprompt`. Fires before the content-based rules
   because the user's first message rides along inside this call
   and would otherwise look like a real turn start.
3. If `content` is a string (not an array of blocks), the request is
   an internal sub-prompt that Claude Code generated rather than a
   user-typed turn — e.g. the `/compact` summarize call, the
   `[SUGGESTION MODE: ...]` autocomplete probe, or the "user stepped
   away" recap.
4. If any block in `content` is a `tool_result`, this request is a
   continuation of a turn already in flight.
5. The `<session>...</session>` wrapper signature on the last text
   block, *without* a Claude Code system prompt, identifies a real
   `claude-manage` probe that doesn't ride Claude Code (rare —
   essentially never in production today since claude-manage proxies
   Claude Code's own requests).
6. Otherwise, walking the content array from the end and skipping
   Claude Code's synthesised wrapper blocks (`<system-reminder>`,
   `<local-command-*>`, `<command-*>`, post-compact resume marker),
   the first remaining text block is what the user actually typed
   — `user_input_turn_start`.

Slash command extraction scans the content array for
`<command-name>/foo</command-name>` markers. /clear, /compact, and
custom skills all surface this way.

`first_msg_hash` is SHA-256[:16] of the **canonical user-typed text**
extracted from `messages[0]` (ADR-0036). Two same-text first
messages collapse to the same hash regardless of containment shape:
the `<session>`-wrapped sidecar (string content), the main-flow
exchange (list content with leading `<system-reminder>` wrappers),
and subsequent turns (which resend the same `messages[0]`) all hash
identically. Wrapper stripping reuses the same
`_SYNTHETIC_WRAPPER_PREFIXES` set the classifier uses for rule 6.
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

# Per-message display vocabulary (ADR-0037). Stored in
# `conversation_messages.role`. Diverges from `TurnKind`: this vocab
# separates the session-start system prompt from the first user input
# (`system_prompt` / `user_input`), splits title-gen sidecars out of
# the catch-all internal subprompt bucket (`title_gen`), and uses
# `model_output` for assistant turns. Non-title-gen sidecars
# (SUGGESTION MODE, `/compact` summarize, step-away recap) and
# tool_result continuations both fold into `assistant` per operator
# direction (2026-05-25).
MessageRole = Literal[
    "system_prompt",
    "user_input",
    "title_gen",
    "model_output",
    "assistant",
]

# Backwards-compatibility alias — code imported `MessageOrigin` before
# ADR-0037. Kept as an alias rather than deleted to avoid churn in
# downstream callers; new code uses `MessageRole`.
MessageOrigin = MessageRole

# Roles a stored `conversation_messages` row can be overwritten *from*
# by the priority UPSERT in `plugin.py`. Under ADR-0037 only `title_gen`
# is a sidecar placeholder (the title-gen probe fires before the main
# flow lands real content at the same msg_index). Real-content arrivals
# (`system_prompt`, `user_input`, `model_output`, `assistant`) displace
# title_gen; sidecar arrivals never displace real content.
OVERWRITABLE_ROLES: frozenset[str] = frozenset({"title_gen"})

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

# Substring signature of Claude Code's title-generation system prompt.
# Appears verbatim in the `system` field of every per-session title
# fetch (observed 2026-05-19 against cc_version=2.1.144).
_TITLE_GEN_SIGNATURE = "Generate a concise, sentence-case title"

# Substring that marks a Claude Code-originated request, distinguishing
# it from a raw claude-manage probe. Used to gate the `<session>` rule.
_CC_SYSTEM_SIGNATURE = "You are Claude Code, Anthropic's official CLI"

# Strips a `<session>\n…\n</session>` wrapper to recover the user-typed
# text inside. ADR-0036: the session-classify sidecar Claude Code fires
# at session start carries the same user input as the main flow, just
# wrapped — stripping the wrapper lets both hash to the same canonical
# string so they share a `conversation_id`.
_SESSION_WRAP_RE = re.compile(r"^\s*<session>\s*(.*?)\s*</session>\s*$", re.DOTALL)


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

    system_text = _system_text(request)
    last = messages[-1]
    content = last.get("content")
    slash_commands = _extract_slash_commands(content) if isinstance(content, list) else None
    turn_kind = _classify_kind(content, system_text)

    return Classification(
        turn_kind=turn_kind,
        slash_commands=slash_commands,
        first_msg_hash=first_msg_hash,
        n_messages=n,
    )


def _classify_kind(content: Any, system_text: str) -> TurnKind:
    # Rule 2: Claude Code's per-session title fetch. The user's first
    # message rides along inside this call so we must catch it before
    # the content-based rules would otherwise label it a real turn.
    if _TITLE_GEN_SIGNATURE in system_text:
        return "internal_subprompt"

    # Rule 3: string content = Claude Code internal sub-prompt.
    if isinstance(content, str):
        return "internal_subprompt"

    if not isinstance(content, list) or not content:
        # No content blocks: treat as continuation (impossible-shape).
        return "tool_continuation"

    # Rule 4: tool_result anywhere in the array = mid-turn continuation.
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

    # Rule 5: real claude-manage probe — `<session>` wrapper without
    # Claude Code as the originator. Effectively dead code in production
    # (claude-manage proxies Claude Code), but the label stays in vocab
    # for the offline / out-of-band probe case.
    if last_text.startswith("<session>") and _CC_SYSTEM_SIGNATURE not in system_text:
        return "claude_manage_probe"

    # Rule 6: walk blocks from end, skip synthesised wrappers; first
    # remaining text block = real user input. Shared helper keeps the
    # definition aligned with `_canonical_user_text` (ADR-0036).
    if _last_real_user_text(content) is not None:
        return "user_input_turn_start"

    # Only synthesised wrappers — no real user text. Treat as
    # continuation (e.g. tool_result-less injected reminder).
    return "tool_continuation"


def _system_text(request: dict[str, Any]) -> str:
    """Concatenate all text in the request's `system` field.

    Anthropic's API accepts either a plain string or a list of
    `{type:'text', text:'…'}` blocks. We sniff for substrings, so
    flattening to one string is enough.
    """
    sys = request.get("system")
    if isinstance(sys, str):
        return sys
    if not isinstance(sys, list):
        return ""
    parts: list[str] = []
    for block in sys:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


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
    """SHA-256[:16] of `messages[0]`'s canonical user-typed text.

    ADR-0036: hashing the *user-typed* text (rather than the raw
    container) means the session-classify sidecar (string content
    wrapped in `<session>...</session>`), the main-flow exchange
    (list content with leading `<system-reminder>` wrappers), and
    every subsequent turn (which resends the same `messages[0]`) all
    produce the same hash and share a `conversation_id` via the
    chain-lookup (B) rule.
    """
    canonical = _canonical_user_text(first.get("content"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _canonical_user_text(content: Any) -> str:
    """Extract the user-typed text from a message's `content` field.

    String content: strip a surrounding `<session>...</session>`
    wrapper if present, then return the inner text. Otherwise return
    the string as-is.

    List content: walk blocks in reverse, skip blocks whose `text`
    starts with any synthetic wrapper prefix
    (`_SYNTHETIC_WRAPPER_PREFIXES`), and return the first remaining
    text block. If no such block exists (only wrappers, or only
    non-text blocks), return the empty string.

    Other shapes (None, dict, etc.): return the empty string.
    """
    if isinstance(content, str):
        m = _SESSION_WRAP_RE.match(content)
        return m.group(1) if m else content
    if isinstance(content, list):
        text = _last_real_user_text(content)
        return text if text is not None else ""
    return ""


def _last_real_user_text(content: list[Any]) -> str | None:
    """Return the last text block whose text is not a synthetic wrapper.

    Walks `content` in reverse and skips blocks whose text starts
    with any prefix in `_SYNTHETIC_WRAPPER_PREFIXES`. Returns the
    raw (left-stripped) text of the first remaining text block, or
    `None` if every text block is a synthetic wrapper.

    Shared between rule 6 in `_classify_kind` and
    `_canonical_user_text` so both definitions of "the user's typed
    text in this message" remain in sync.
    """
    for b in reversed(content):
        if _block_type(b) != "text":
            continue
        text = (b.get("text") or "").lstrip()
        if text.startswith(_SYNTHETIC_WRAPPER_PREFIXES):
            continue
        return text
    return None


def classify_message(msg: dict[str, Any]) -> MessageRole:
    """Classify a single Anthropic Messages API message by display role.

    ADR-0037 vocab. Returns one of:

    * ``"model_output"`` — `role=assistant`.
    * ``"title_gen"`` — string content whose payload is a
      `<session>...</session>` wrapper (Claude Code's per-session
      title fetch carries the user's first message inside this shape).
    * ``"assistant"`` — every other framework-synthesised message
      Claude Code emits with `role=user`: `/compact` summarize,
      `[SUGGESTION MODE: ...]`, step-away recap, tool_result
      continuations, and list content whose only text blocks are
      synthetic wrappers (post-`/compact` resume marker, etc.).
    * ``"user_input"`` — list content with at least one non-wrapper
      text block (the user's typed text).

    `system_prompt` is **never emitted** from this function — it is
    only assigned by `split_first_message` when `messages[0]` carries
    leading wrapper blocks. A caller iterating messages should call
    `split_first_message` on index 0 first; if it returns a split,
    persist the system_prompt slice with role=`system_prompt` and the
    user_input slice with role=`user_input`, then continue iterating
    from index 1 with `classify_message`.
    """
    if msg.get("role") == "assistant":
        return "model_output"

    content = msg.get("content")

    # title_gen: bare string payload wrapped in `<session>...</session>`.
    # Per-message scope has no `system` field to disambiguate, so we
    # match on the wrapper shape alone — production data (2026-05-25)
    # shows this shape only appears for title-gen sidecars and the
    # one historic mislabel that the new vocab now classifies correctly.
    if isinstance(content, str):
        if _SESSION_WRAP_RE.match(content):
            return "title_gen"
        # Other string sub-prompts (/compact, SUGGESTION, step-away).
        return "assistant"

    # title_gen, list shape: Claude Code's title-gen sidecar arrives over
    # HTTP as a single bare text block whose text is the full
    # `<session>...</session>` payload; the canonical_message normaliser
    # later collapses it to a bare string (Rule B), but classification
    # runs on the un-normalised dict, so this branch must catch the
    # list-of-one form before falling through to user_input.
    if isinstance(content, list) and len(content) == 1:
        only = content[0]
        if (
            isinstance(only, dict)
            and _block_type(only) == "text"
            and _SESSION_WRAP_RE.match(only.get("text") or "")
        ):
            return "title_gen"

    if isinstance(content, list) and any(_block_type(b) == "tool_result" for b in content):
        return "assistant"

    if not isinstance(content, list) or not content:
        return "assistant"

    if _last_real_user_text(content) is not None:
        return "user_input"

    # Only synthetic wrappers — system sidecar.
    return "assistant"


def split_first_message(
    msg: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Split `messages[0]` into a system_prompt slice and a user_input slice.

    The Anthropic Messages API delivers Claude Code's session opener
    as a single user message whose content is a list of text blocks:
    leading `<system-reminder>` (and friends) followed by the user's
    typed text. Storing that as one row obscures the user's actual
    input. Splitting it into two `conversation_messages` rows under
    ADR-0037:

    * ``msg_index = 0``, role=`system_prompt`, content=the wrapper
      blocks (preserved as a list so the original framing is intact).
    * ``msg_index = 1``, role=`user_input`, content=the trailing
      non-wrapper blocks.

    The downstream caller is responsible for shifting subsequent
    msg_index values by +1 (and adjusting `n_messages_at_request`
    accordingly) when a split is taken.

    Returns ``None`` when no split applies:

    * Content is a string (title_gen sidecar, internal sub-prompt).
    * Content is a list with no leading wrapper block.
    * Content is a list where every text block is a synthetic wrapper
      (no real user text to peel off).
    * `msg.role != "user"` (assistant never carries wrappers).
    """
    if msg.get("role") != "user":
        return None
    content = msg.get("content")
    if not isinstance(content, list) or not content:
        return None

    # Walk blocks from the start, peeling wrapper text blocks into the
    # system_prompt slice. The first block that is NOT a wrapper text
    # ends the system_prompt and starts user_input; everything from
    # that point onward stays in user_input (including any non-text
    # blocks like tool_use, which are not expected at messages[0] but
    # preserved defensively).
    system_blocks: list[dict[str, Any]] = []
    user_blocks: list[dict[str, Any]] = []
    split_point: int | None = None
    for idx, b in enumerate(content):
        if not isinstance(b, dict):
            split_point = idx
            break
        if _block_type(b) != "text":
            split_point = idx
            break
        text = (b.get("text") or "").lstrip()
        if text.startswith(_SYNTHETIC_WRAPPER_PREFIXES):
            system_blocks.append(b)
            continue
        split_point = idx
        break

    if split_point is None or not system_blocks:
        # No wrapper-prefixed lead, or every block was a wrapper.
        # Either way there is nothing to peel off as system_prompt.
        return None

    user_blocks = list(content[split_point:])
    if not user_blocks:
        return None

    user_msg = {"role": "user", "content": user_blocks}
    return system_blocks, user_msg


def _block_type(block: Any) -> str | None:
    if not isinstance(block, dict):
        return None
    t = block.get("type")
    return t if isinstance(t, str) else None
