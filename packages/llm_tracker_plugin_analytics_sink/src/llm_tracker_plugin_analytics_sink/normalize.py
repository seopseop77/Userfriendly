"""Canonicalise an Anthropic Messages API message for dedup.

Used as the input to the `conversation_messages.content_jsonb` column.
See `docs/worklog/2026-05-19-candidate-1-handoff.md` §3 for the
empirical derivation of these two rules from the STRESS-1 ~ STRESS-6
run against main conv `01KS084X32YARSRKGBY35ACRYM`.

Rule A: drop `cache_control` from every content block — prompt-caching
breakpoints move between rows but the content is otherwise identical.

Rule B: collapse a single bare `{type:"text",text:"X"}` array to the
bare string `"X"` — the Anthropic SDK serialises a user message that
way on the first send and re-sends it as a bare string on every
subsequent turn.

Other dynamic-looking fields (`tool_use.id`, `tool_result.tool_use_id`,
extended-thinking `signature`) were verified stable across rows in the
same run and are NOT normalised.
"""

from __future__ import annotations

from typing import Any

_DROPPED_BLOCK_KEYS: frozenset[str] = frozenset({"cache_control"})


def canonical_message(m: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical `(role, content)` form used as the dedup key."""
    role = m.get("role")
    content = _canonical_content(m.get("content"))
    return {"role": role, "content": content}


def _canonical_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return content
    blocks = [_drop_dropped_keys(b) for b in content if isinstance(b, dict)]
    # Rule B: a single bare text block collapses to the bare string.
    if (
        len(blocks) == 1
        and blocks[0].get("type") == "text"
        and set(blocks[0].keys()) == {"type", "text"}
    ):
        return blocks[0]["text"]
    return blocks


def _drop_dropped_keys(block: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in block.items() if k not in _DROPPED_BLOCK_KEYS}
