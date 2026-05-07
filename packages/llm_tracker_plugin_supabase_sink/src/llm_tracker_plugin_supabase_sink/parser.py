"""Anthropic request/response parsers for the supabase_sink plugin.

Two responsibilities:

- `ResponseAssembler` accumulates streamed Anthropic SSE bytes into the
  response text + usage + stop_reason. Mirrors the token_counter
  pattern; extends it to also collect `text_delta` events into a
  human-readable response string and produces a compact
  `raw_response_summary` dict for the `raw_response` jsonb column.

- `extract_request_text` decodes the cached request body and renders
  `system` + `messages[]` into a human-readable string. `image` blocks
  are replaced with the literal token `[image]` so we don't ship base64
  payloads to Supabase. Tool blocks are rendered compactly.

Both are intentionally small, dependency-free, and self-contained — when
the Phase-2 Extractor lands, this parser graduates to the SDK or gets
replaced wholesale.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Block:
    """One Anthropic content block as the assembler sees it across deltas."""

    type: str
    text: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)


class ResponseAssembler:
    """Per-exchange Anthropic SSE accumulator.

    Buffers raw bytes across chunk boundaries (handles both `\\n\\n` and
    `\\r\\n\\r\\n` event terminators — some HTTP stacks insert CRLF),
    parses each completed `event: ... \\n data: ...` block, and tracks:

    - `model` (from `message_start.message.model`)
    - `stop_reason` (from `message_delta.delta.stop_reason`)
    - `input_tokens`, `output_tokens`, `cache_creation_input_tokens`,
      `cache_read_input_tokens` — taking the *max* across `message_start`
      and `message_delta` since the latter carries the cumulative final
      value (same semantics as token_counter).
    - `response_text` (text-only blocks joined by `\\n\\n` in index order)
    - `raw_response_summary` (compact dict suitable for `raw_response jsonb`)

    Bytes that don't decode as UTF-8 cause the offending event block to
    be dropped silently — the assembler must never raise into the proxy
    pipeline.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self.model: str | None = None
        self.stop_reason: str | None = None
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cache_creation_input_tokens: int = 0
        self.cache_read_input_tokens: int = 0
        self._blocks: dict[int, _Block] = {}

    # -- input ------------------------------------------------------------

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._buf.extend(chunk)
        # Pop completed events one at a time. Use whichever terminator
        # appears first in the buffer (`\n\n` is the SSE spec; `\r\n\r\n`
        # is what some upstream stacks produce).
        while True:
            idx_lf = self._buf.find(b"\n\n")
            idx_crlf = self._buf.find(b"\r\n\r\n")
            if idx_lf < 0 and idx_crlf < 0:
                break
            if idx_lf < 0:
                end, term_len = idx_crlf, 4
            elif idx_crlf < 0:
                end, term_len = idx_lf, 2
            elif idx_crlf < idx_lf:
                end, term_len = idx_crlf, 4
            else:
                end, term_len = idx_lf, 2
            block = bytes(self._buf[:end])
            del self._buf[: end + term_len]
            self._consume_block(block)

    # -- block parsing ----------------------------------------------------

    def _consume_block(self, block: bytes) -> None:
        event_name: str | None = None
        data_lines: list[str] = []
        for raw_line in block.split(b"\n"):
            try:
                line = raw_line.decode("utf-8").rstrip("\r")
            except UnicodeDecodeError:
                return
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if event_name is None or not data_lines:
            return
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict):
            self._apply(event_name, payload)

    def _apply(self, event: str, payload: dict[str, Any]) -> None:
        if event == "message_start":
            msg = payload.get("message")
            if isinstance(msg, dict):
                model = msg.get("model")
                if isinstance(model, str):
                    self.model = model
                usage = msg.get("usage")
                if isinstance(usage, dict):
                    self._merge_usage(usage)
        elif event == "content_block_start":
            idx = payload.get("index")
            cb = payload.get("content_block")
            if isinstance(idx, int) and isinstance(cb, dict):
                ctype = cb.get("type")
                if isinstance(ctype, str):
                    initial_text = cb.get("text", "")
                    self._blocks[idx] = _Block(
                        type=ctype,
                        text=initial_text if isinstance(initial_text, str) else "",
                        payload=cb,
                    )
        elif event == "content_block_delta":
            idx = payload.get("index")
            delta = payload.get("delta")
            if (
                isinstance(idx, int)
                and idx in self._blocks
                and isinstance(delta, dict)
                and delta.get("type") == "text_delta"
            ):
                piece = delta.get("text", "")
                if isinstance(piece, str):
                    self._blocks[idx].text += piece
        elif event == "message_delta":
            d = payload.get("delta")
            if isinstance(d, dict):
                stop_reason = d.get("stop_reason")
                if isinstance(stop_reason, str):
                    self.stop_reason = stop_reason
            usage = payload.get("usage")
            if isinstance(usage, dict):
                self._merge_usage(usage)
        # content_block_stop / message_stop / unknown events: no-op

    def _merge_usage(self, usage: Mapping[str, Any]) -> None:
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            value = usage.get(key)
            if isinstance(value, int):
                cur = getattr(self, key)
                if value > cur:
                    setattr(self, key, value)

    # -- output -----------------------------------------------------------

    @property
    def response_text(self) -> str:
        """Text-only blocks joined by `\\n\\n` in index order."""
        parts = [b.text for _, b in sorted(self._blocks.items()) if b.type == "text" and b.text]
        return "\n\n".join(parts)

    def raw_response_summary(self) -> dict[str, Any]:
        """Compact dict suitable for the `raw_response jsonb` column.

        Captures the structural shape (block types, text content, usage,
        stop_reason, model) without retaining the full SSE event log —
        keeping the row size bounded.
        """
        return {
            "model": self.model,
            "stop_reason": self.stop_reason,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cache_creation_input_tokens": self.cache_creation_input_tokens,
                "cache_read_input_tokens": self.cache_read_input_tokens,
            },
            "blocks": [
                {"index": i, "type": b.type, "text": b.text}
                if b.type == "text"
                else {"index": i, "type": b.type}
                for i, b in sorted(self._blocks.items())
            ],
        }


# -- request extraction ---------------------------------------------------


def extract_request_text(body: bytes | None) -> tuple[str, dict[str, Any] | None]:
    """Decode an Anthropic Messages request body and render readable text.

    Returns `(request_text, raw_request_dict)`:

    - `request_text` concatenates `system` + every `messages[i]` block,
      labelling each section with its role. Image blocks are replaced
      with the literal token `[image]` so we never ship base64 payloads
      to Supabase. Tool blocks are rendered compactly for analysis.
    - `raw_request_dict` is the full parsed JSON body, suitable for the
      `raw_request jsonb` column. `None` on parse failure or non-dict
      bodies.

    Failure modes (all return `("", None)`): empty body, non-UTF-8 bytes,
    invalid JSON, top-level non-object.
    """
    if not body:
        return "", None
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        return "", None
    try:
        parsed = json.loads(decoded)
    except json.JSONDecodeError:
        return "", None
    if not isinstance(parsed, dict):
        return "", None

    parts: list[str] = []

    system = parsed.get("system")
    rendered_system = _render_content(system)
    if rendered_system:
        parts.append(f"[system]\n{rendered_system}")

    messages = parsed.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            role_str = role if isinstance(role, str) else "?"
            rendered = _render_content(msg.get("content"))
            if rendered:
                parts.append(f"[{role_str}]\n{rendered}")

    return "\n\n".join(parts), parsed


def _render_content(content: Any) -> str:
    """Render Anthropic `content` (string OR list of blocks) into a string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _render_blocks(content)
    return ""


def _render_blocks(blocks: list[Any]) -> str:
    rendered: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                rendered.append(text)
        elif btype == "image":
            rendered.append("[image]")
        elif btype == "tool_use":
            name = block.get("name")
            name_str = name if isinstance(name, str) else "?"
            try:
                input_str = json.dumps(block.get("input"), ensure_ascii=False)
            except (TypeError, ValueError):
                input_str = repr(block.get("input"))
            rendered.append(f"[tool_use {name_str}({input_str})]")
        elif btype == "tool_result":
            tool_id = block.get("tool_use_id")
            tool_id_str = tool_id if isinstance(tool_id, str) else "?"
            inner = _render_content(block.get("content"))
            rendered.append(
                f"[tool_result {tool_id_str}]\n{inner}" if inner else f"[tool_result {tool_id_str}]"
            )
        # unknown block types are skipped
    return "\n\n".join(rendered)
