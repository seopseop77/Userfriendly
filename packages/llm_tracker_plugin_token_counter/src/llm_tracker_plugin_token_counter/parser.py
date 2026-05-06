"""Streaming Anthropic SSE accumulator (test-only).

The proxy hands us raw SSE bytes one chunk at a time; events may straddle
chunk boundaries. We buffer until we see the `\\n\\n` terminator and then
extract `event:` / `data:` lines per the SSE wire format.

Only two event kinds carry usage data:
- `message_start`: `data.message.usage.{input_tokens, output_tokens,
  cache_creation_input_tokens, cache_read_input_tokens}` plus model name.
- `message_delta`: `data.usage.output_tokens` (cumulative final count).

Anything else is ignored.
"""

from __future__ import annotations

import json


class UsageAccumulator:
    """Per-exchange running totals + an SSE byte buffer."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._saw_usage = False
        self.model: str | None = None
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cache_creation_input_tokens: int = 0
        self.cache_read_input_tokens: int = 0

    def has_usage(self) -> bool:
        return self._saw_usage

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._buf.extend(chunk)
        # SSE event boundary is a blank line. Pop completed events one by one.
        while True:
            idx = self._buf.find(b"\n\n")
            if idx < 0:
                break
            block = bytes(self._buf[:idx])
            del self._buf[: idx + 2]
            self._consume_block(block)

    def _consume_block(self, block: bytes) -> None:
        event_name: str | None = None
        data_lines: list[str] = []
        for raw_line in block.split(b"\n"):
            try:
                line = raw_line.decode("utf-8")
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
        self._apply(event_name, payload)

    def _apply(self, event_name: str, payload: dict) -> None:
        if event_name == "message_start":
            message = payload.get("message") or {}
            usage = message.get("usage") or {}
            model = message.get("model")
            if isinstance(model, str):
                self.model = model
            self._merge_usage(usage)
        elif event_name == "message_delta":
            usage = payload.get("usage") or {}
            self._merge_usage(usage)

    def _merge_usage(self, usage: dict) -> None:
        # Anthropic's `message_delta.usage.output_tokens` is the final
        # cumulative count, so taking the max of every value we see lands
        # on the right total whether `message_start` carried a partial or
        # zero placeholder.
        applied = False
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            value = usage.get(key)
            if not isinstance(value, int):
                continue
            current = getattr(self, key)
            if value > current:
                setattr(self, key, value)
            applied = True
        if applied:
            self._saw_usage = True


__all__ = ["UsageAccumulator"]
