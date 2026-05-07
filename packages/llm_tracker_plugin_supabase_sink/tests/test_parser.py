"""Unit tests for the supabase_sink parser (ADR-0007 reference plugin).

`ResponseAssembler` covers the SSE-side; `extract_request_text` covers
the request-body side. The two are exercised independently here; CP6
will add lifecycle/integration tests that wire them together with the
client and the queue.
"""

from __future__ import annotations

import json

from llm_tracker_plugin_supabase_sink.parser import (
    ResponseAssembler,
    extract_request_text,
)

# -- SSE byte builders ------------------------------------------------------


def _sse_lf(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def _sse_crlf(event: str, data: dict) -> bytes:
    """Some HTTP stacks emit CRLF terminators."""
    return f"event: {event}\r\ndata: {json.dumps(data, separators=(',', ':'))}\r\n\r\n".encode()


def _msg_start(
    *, model: str = "claude-test", input_tokens: int = 0, output_tokens: int = 0
) -> dict:
    return {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    }


def _block_start(index: int, btype: str = "text", **kwargs) -> dict:
    return {
        "type": "content_block_start",
        "index": index,
        "content_block": {"type": btype, **kwargs},
    }


def _text_delta(index: int, text: str) -> dict:
    return {
        "type": "content_block_delta",
        "index": index,
        "delta": {"type": "text_delta", "text": text},
    }


def _block_stop(index: int) -> dict:
    return {"type": "content_block_stop", "index": index}


def _msg_delta(*, stop_reason: str | None = "end_turn", output_tokens: int | None = None) -> dict:
    payload: dict = {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
    }
    if output_tokens is not None:
        payload["usage"] = {"output_tokens": output_tokens}
    return payload


def _msg_stop() -> dict:
    return {"type": "message_stop"}


# -- ResponseAssembler ------------------------------------------------------


def test_response_text_collects_text_deltas_in_order():
    asm = ResponseAssembler()
    asm.feed(_sse_lf("message_start", _msg_start()))
    asm.feed(_sse_lf("content_block_start", _block_start(0, "text", text="")))
    asm.feed(_sse_lf("content_block_delta", _text_delta(0, "Hello, ")))
    asm.feed(_sse_lf("content_block_delta", _text_delta(0, "world!")))
    asm.feed(_sse_lf("content_block_stop", _block_stop(0)))
    asm.feed(_sse_lf("message_delta", _msg_delta(stop_reason="end_turn", output_tokens=4)))
    asm.feed(_sse_lf("message_stop", _msg_stop()))

    assert asm.response_text == "Hello, world!"
    assert asm.model == "claude-test"
    assert asm.stop_reason == "end_turn"
    assert asm.output_tokens == 4


def test_response_text_joins_multiple_text_blocks_with_blank_lines():
    asm = ResponseAssembler()
    asm.feed(_sse_lf("message_start", _msg_start()))
    asm.feed(_sse_lf("content_block_start", _block_start(0, "text", text="")))
    asm.feed(_sse_lf("content_block_delta", _text_delta(0, "First.")))
    asm.feed(_sse_lf("content_block_stop", _block_stop(0)))
    asm.feed(_sse_lf("content_block_start", _block_start(1, "text", text="")))
    asm.feed(_sse_lf("content_block_delta", _text_delta(1, "Second.")))
    asm.feed(_sse_lf("content_block_stop", _block_stop(1)))

    assert asm.response_text == "First.\n\nSecond."


def test_response_text_skips_non_text_blocks():
    """tool_use blocks must not appear in response_text (they live in raw_response)."""
    asm = ResponseAssembler()
    asm.feed(_sse_lf("message_start", _msg_start()))
    asm.feed(
        _sse_lf(
            "content_block_start",
            _block_start(0, "tool_use", id="t1", name="get_weather", input={}),
        )
    )
    asm.feed(_sse_lf("content_block_stop", _block_stop(0)))
    asm.feed(_sse_lf("content_block_start", _block_start(1, "text", text="Done.")))
    asm.feed(_sse_lf("content_block_stop", _block_stop(1)))

    assert asm.response_text == "Done."


def test_assembler_handles_chunk_split_mid_event():
    """Bytes split inside a `data:` line must still produce the full payload."""
    full = (
        _sse_lf("message_start", _msg_start())
        + _sse_lf("content_block_start", _block_start(0, "text", text=""))
        + _sse_lf("content_block_delta", _text_delta(0, "Hello"))
        + _sse_lf("content_block_stop", _block_stop(0))
    )
    asm = ResponseAssembler()
    # Feed one byte at a time — the worst-case fragmentation.
    for i in range(len(full)):
        asm.feed(full[i : i + 1])
    assert asm.response_text == "Hello"


def test_assembler_handles_crlf_event_terminator():
    asm = ResponseAssembler()
    asm.feed(_sse_crlf("message_start", _msg_start()))
    asm.feed(_sse_crlf("content_block_start", _block_start(0, "text", text="")))
    asm.feed(_sse_crlf("content_block_delta", _text_delta(0, "CRLF")))
    asm.feed(_sse_crlf("content_block_stop", _block_stop(0)))

    assert asm.response_text == "CRLF"


def test_assembler_mixes_lf_and_crlf_terminators():
    asm = ResponseAssembler()
    asm.feed(_sse_lf("message_start", _msg_start()))
    asm.feed(_sse_crlf("content_block_start", _block_start(0, "text", text="")))
    asm.feed(_sse_lf("content_block_delta", _text_delta(0, "mixed")))
    asm.feed(_sse_crlf("content_block_stop", _block_stop(0)))

    assert asm.response_text == "mixed"


def test_usage_takes_max_across_message_start_and_message_delta():
    """Anthropic streams `output_tokens` in `message_delta` as the cumulative final."""
    asm = ResponseAssembler()
    asm.feed(_sse_lf("message_start", _msg_start(input_tokens=12, output_tokens=0)))
    asm.feed(_sse_lf("message_delta", _msg_delta(output_tokens=42)))
    assert asm.input_tokens == 12
    assert asm.output_tokens == 42  # final cumulative wins


def test_assembler_skips_unknown_event_types():
    asm = ResponseAssembler()
    asm.feed(_sse_lf("ping", {"type": "ping"}))
    asm.feed(_sse_lf("future_unknown", {"foo": "bar"}))
    asm.feed(_sse_lf("message_start", _msg_start()))
    asm.feed(_sse_lf("content_block_start", _block_start(0, "text", text="")))
    asm.feed(_sse_lf("content_block_delta", _text_delta(0, "ok")))
    assert asm.response_text == "ok"


def test_assembler_drops_event_with_invalid_json_data():
    """Malformed `data:` lines must not raise into the proxy pipeline."""
    asm = ResponseAssembler()
    asm.feed(b"event: message_start\ndata: { not json\n\n")
    asm.feed(_sse_lf("message_start", _msg_start(input_tokens=5)))
    # Bad block was dropped silently; good block applied.
    assert asm.input_tokens == 5


def test_assembler_drops_non_utf8_chunk_segment():
    asm = ResponseAssembler()
    # Inject invalid UTF-8 inside a complete event block; the offending
    # block is dropped, but subsequent valid blocks still apply.
    asm.feed(b"event: message_start\ndata: \xff\xfe\n\n")
    asm.feed(_sse_lf("message_start", _msg_start(input_tokens=7)))
    assert asm.input_tokens == 7


def test_raw_response_summary_shape():
    asm = ResponseAssembler()
    asm.feed(_sse_lf("message_start", _msg_start(input_tokens=10, output_tokens=0)))
    asm.feed(_sse_lf("content_block_start", _block_start(0, "text", text="")))
    asm.feed(_sse_lf("content_block_delta", _text_delta(0, "abc")))
    asm.feed(_sse_lf("content_block_stop", _block_stop(0)))
    asm.feed(_sse_lf("message_delta", _msg_delta(stop_reason="end_turn", output_tokens=3)))

    summary = asm.raw_response_summary()
    assert summary["model"] == "claude-test"
    assert summary["stop_reason"] == "end_turn"
    assert summary["usage"] == {
        "input_tokens": 10,
        "output_tokens": 3,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    assert summary["blocks"] == [{"index": 0, "type": "text", "text": "abc"}]


# -- extract_request_text --------------------------------------------------


def _enc(payload: dict) -> bytes:
    return json.dumps(payload).encode()


def test_extract_string_content():
    text, raw = extract_request_text(_enc({"messages": [{"role": "user", "content": "hi"}]}))
    assert text == "[user]\nhi"
    assert raw is not None
    assert raw["messages"][0]["content"] == "hi"


def test_extract_list_of_text_blocks():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": "second"},
                ],
            }
        ]
    }
    text, _ = extract_request_text(_enc(body))
    assert text == "[user]\nfirst\n\nsecond"


def test_extract_image_block_replaced_with_placeholder():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look:"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "iVBORw0KGgoAAAANSUhEUgAA" * 1000,  # large
                        },
                    },
                ],
            }
        ]
    }
    text, raw = extract_request_text(_enc(body))
    assert "[image]" in text
    # Critical: the rendered text must NOT contain the base64 payload.
    assert "iVBORw0KGgoAAAANSUhEUgAA" not in text
    # raw_request preserves the original (it's just a JSON dump for forensics).
    assert raw["messages"][0]["content"][1]["type"] == "image"


def test_extract_tool_use_block_renders_with_input():
    body = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "get_weather",
                        "input": {"city": "Seoul"},
                    }
                ],
            }
        ]
    }
    text, _ = extract_request_text(_enc(body))
    assert text.startswith("[assistant]\n")
    assert "[tool_use get_weather(" in text
    assert '"city": "Seoul"' in text or '"city":"Seoul"' in text


def test_extract_tool_result_block_with_string_content():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": "sunny, 22C",
                    }
                ],
            }
        ]
    }
    text, _ = extract_request_text(_enc(body))
    assert "[tool_result t1]\nsunny, 22C" in text


def test_extract_tool_result_block_with_list_content():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t2",
                        "content": [{"type": "text", "text": "rainy"}],
                    }
                ],
            }
        ]
    }
    text, _ = extract_request_text(_enc(body))
    assert "[tool_result t2]\nrainy" in text


def test_extract_top_level_system_string():
    body = {
        "system": "You are concise.",
        "messages": [{"role": "user", "content": "hi"}],
    }
    text, _ = extract_request_text(_enc(body))
    assert text.startswith("[system]\nYou are concise.\n\n[user]\nhi")


def test_extract_top_level_system_block_list():
    """Anthropic also accepts `system` as a list of text blocks (with cache_control etc.)."""
    body = {
        "system": [{"type": "text", "text": "block-style system"}],
        "messages": [{"role": "user", "content": "hi"}],
    }
    text, _ = extract_request_text(_enc(body))
    assert "[system]\nblock-style system" in text


def test_extract_handles_invalid_json_gracefully():
    text, raw = extract_request_text(b"{not json")
    assert text == ""
    assert raw is None


def test_extract_handles_empty_body():
    assert extract_request_text(b"") == ("", None)
    assert extract_request_text(None) == ("", None)


def test_extract_handles_missing_messages_field():
    """A body with no `messages` and no `system` produces empty text."""
    text, raw = extract_request_text(_enc({"model": "claude-test"}))
    assert text == ""
    assert raw == {"model": "claude-test"}


def test_extract_skips_non_dict_messages_entries():
    body = {"messages": ["not a dict", {"role": "user", "content": "ok"}]}
    text, _ = extract_request_text(_enc(body))
    assert text == "[user]\nok"


def test_extract_handles_non_utf8_body():
    text, raw = extract_request_text(b"\xff\xfe not utf-8")
    assert text == ""
    assert raw is None


def test_extract_handles_top_level_non_object():
    text, raw = extract_request_text(_enc(["array", "not", "object"]))
    assert text == ""
    assert raw is None


def test_extract_skips_unknown_block_types():
    """Forward-compatibility: unknown block types are dropped, not raised."""
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "future_block_type", "data": "skip me"},
                    {"type": "text", "text": "kept"},
                ],
            }
        ]
    }
    text, _ = extract_request_text(_enc(body))
    assert text == "[user]\nkept"
