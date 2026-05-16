# 2026-05-16 · Extractor `response_json` — faithful reassembly (ADR-0028)

**Author**: Claude Code
**Session trigger**: User pointed out a live `plugin_analytics` row where
`response_json = {"content": [], "stop_reason": "tool_use", "usage":
{"output_tokens": 112, ...}}`. The model emitted 112 tokens of tool-use
payload, the proxy forwarded them intact (Claude Code received the tool_use
and invoked the tool), but the durable analytics row stored an empty
`content`. User's framing: "`response_json`은 모델이 출력한 모든 정보를
담아야 한다; 분석은 이후의 분석 코드에서 알아서 처리하면 된다."
**Related docs**: `docs/decisions/0028-extractor-faithful-response-reassembly.md`
(new), ADR-0026 (HookContext response accessors — surface), ADR-0027 (NULL
policy for the summary columns), prior worklog
`docs/worklog/2026-05-14-plugin-ecosystem.md` (Option B SSE extractor that
introduced the text-only narrow path).

## Interpretation

Two interpretations of `response_json`'s contract were on the table:

- **A. Curated summary.** Extract what the central server has a use for
  (text content + token counts); ignore everything else. Each new Anthropic
  block type requires a server-side extractor change. "Empty content under a
  tool_use stop_reason" is the visible failure of A.
- **B. Faithful reassembly.** Reproduce Anthropic's non-stream response shape
  verbatim. New block types preserved best-effort. The column keeps its
  promise.

User picked B explicitly. I also raised `tool_call_count` on `exchanges` as
a candidate sibling fix; user pushed back ("derived field belongs in the
analysis layer, not stored alongside the canonical body"), which is
internally consistent with B and dropped from scope.

Single ADR (0028) rather than amending ADR-0026: ADR-0026 is Accepted and
its surface (`response_content_json()`) stays unchanged; this ADR
strengthens the *behind-the-surface contract*, so a sibling Accepted ADR
keeps the history readable. Decision recorded under ADR-0028 §Context /
§Decision.

## What was done

- Created `docs/decisions/0028-extractor-faithful-response-reassembly.md`
  — Accepted. Three reasons in §Decision (storage canonical / forward-compat
  cheap / column name keeps its promise). Names the extractor contract on
  each `content_block_*` event. `tool_calls` and `tool_call_count` flagged
  as non-goals; their fate is a separate decision. (commit `8138d91`)
- Modified
  `packages/llm_tracker_server/src/llm_tracker_server/extractors/anthropic.py`
  — replaced the local `text_blocks: dict[int, list[str]]` accumulator with
  a `_StreamState` dataclass holding `blocks: dict[int, dict]` +
  `input_json_buffers: dict[int, list[str]]`. Three new event handlers:
  `content_block_start` seeds `blocks[index]` from `content_block` as-is;
  `content_block_delta` dispatches by `delta.type` (`text_delta` /
  `input_json_delta` / `thinking_delta` / `signature_delta` / unknown);
  `content_block_stop` calls `_finalize_input_json` which `json.loads` the
  buffered `partial_json` into `block["input"]`, falling back to
  `block["_input_json_raw"]` on parse failure. Module docstring rewritten
  to reflect ADR-0028. (commit `8138d91`)
- Modified `packages/llm_tracker_server/tests/test_sse_extractor.py` — 5
  new tests under the ADR-0028 banner: `test_tool_use_block_assembled` (the
  exact shape the user's row should have carried), `test_mixed_text_and_tool_use_blocks`
  (ordering across indices), `test_thinking_block_assembled`,
  `test_unknown_delta_type_preserved` (fail-open lever), `test_malformed_input_json_preserves_raw`
  (raw-string fallback). (commit `8138d91`)

## Decisions

- **Faithful reassembly wins (Axis 1 of ADR-0028).** Storage is canonical;
  derivation is downstream. Consistent with how `messages_json` already
  stores the request body verbatim.
- **Unknown delta types preserved under `_extra_deltas`, not dropped.**
  Forward-compatibility lever. Future ADRs can promote a specific delta
  type to a typed field once Anthropic stabilizes it.
- **Malformed `input_json` falls back to `_input_json_raw`, not dropped.**
  Same principle as above — the raw bytes are the only thing we have once
  the stream ends; data loss is a one-way door.
- **`tool_call_count` on `exchanges` stays at 0 (placeholder).** Deriving
  it from `response_json.content` is one `jsonb_path_query` per query;
  pre-computed columns duplicate the source. The column's fate
  (deprecate / drop / leave) is queued as a separate decision.
- **One ADR, not an ADR-0026 amendment.** ADR-0026's public surface
  (`response_content_json()`) doesn't change; ADR-0028 strengthens the
  contract behind that surface. Keeping it a sibling Accepted ADR keeps
  the supersede chain clean.

## Verification

Tests under the SSE extractor module:

```
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_server/tests/test_sse_extractor.py -v
============================= test session starts ==============================
packages/.../test_sse_extractor.py::test_parses_model_and_tokens PASSED  [  9%]
packages/.../test_sse_extractor.py::test_partial_stream_no_raise PASSED  [ 18%]
packages/.../test_sse_extractor.py::test_malformed_json_no_raise PASSED  [ 27%]
packages/.../test_sse_extractor.py::test_response_json_assembled PASSED  [ 36%]
packages/.../test_sse_extractor.py::test_chunk_boundary_mid_event PASSED [ 45%]
packages/.../test_sse_extractor.py::test_empty_stream_returns_empty_response PASSED [ 54%]
packages/.../test_sse_extractor.py::test_tool_use_block_assembled PASSED [ 63%]
packages/.../test_sse_extractor.py::test_mixed_text_and_tool_use_blocks PASSED [ 72%]
packages/.../test_sse_extractor.py::test_thinking_block_assembled PASSED [ 81%]
packages/.../test_sse_extractor.py::test_unknown_delta_type_preserved PASSED [ 90%]
packages/.../test_sse_extractor.py::test_malformed_input_json_preserves_raw PASSED [100%]
============================== 11 passed in 0.02s ==============================
```

Ruff + full repo:

```
$ .venv/bin/python3.12 -m ruff format \
    packages/llm_tracker_server/src/llm_tracker_server/extractors/anthropic.py \
    packages/llm_tracker_server/tests/test_sse_extractor.py
1 file reformatted, 1 file left unchanged

$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker_server/src/llm_tracker_server/extractors/anthropic.py \
    packages/llm_tracker_server/tests/test_sse_extractor.py
All checks passed!

$ .venv/bin/python3.12 -m pytest -q     # no DB fixture
318 passed, 16 skipped, 4 warnings in 12.51s
# 5 new tests; was 313 SSE-extractor-only before this CP.

$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest -q
334 passed, 4 warnings in 21.57s
# Was 329 before this CP (DB fixture lifts the 16 skips and adds DB-touching tests).
```

## What's left / known limits

- **Operator-run smoke on Fly.io still pending** (carry-over from the
  2026-05-14 Option B + plugin-ecosystem workstream). The recipe in that
  worklog's "What's left" remains valid; this CP rides into the same
  `fly deploy` and gives the operator's "is `response_json` faithful for
  tool_use rows now?" check a definitive yes.
- **No backfill.** Historical `plugin_analytics` rows with
  `content: []` under a tool_use `stop_reason` cannot be repaired — the
  upstream bytes were not retained. Operator queries on past rows must
  filter `WHERE created_at >= <deploy_time_of_8138d91>`.
- **Response-side scrubbing still owed under ADR-#2** (consent +
  data-handling). Faithful reassembly is compatible with a downstream
  scrubber pass: `extractor → scrubber → storage` once the scrubber
  lands. Until then `plugin_analytics` rows carry raw payloads (request +
  response), which keeps the central server operator-only.
- **`exchanges.tool_call_count` left at 0 placeholder.** Deriving from
  `response_json.content` is one SQL expression per query. Column's fate
  (deprecate / drop / leave) is queued.
- **Pre-SSE upstream failure path row write** (ADR-0027 axis 2 impl)
  remains queued.

## Closure — production smoke validated (2026-05-16)

Operator ran `fly deploy` (advancing the image past `c95e60c`),
re-exercised `claude-manage` against the live server, and confirmed
Supabase rows again. A representative post-deploy `plugin_analytics`
row (shown verbatim by the operator) carried `response_json` of the
shape:

```json
{
  "model": "claude-opus-4-7",
  "content": [
    {"type": "thinking", "thinking": "", "signature": "EoEC..."},
    {"type": "tool_use",
     "id": "toolu_01HgwgDtcBKBChGSpUBQeLoj",
     "name": "Bash",
     "input": {"command": "date \"+%Y-%m-%d %H:%M:%S %Z\"",
               "description": "Print current date and time"}}
  ],
  "stop_reason": "tool_use",
  "usage": {"input_tokens": 6, "output_tokens": 152,
            "cache_read_input_tokens": 75512,
            "cache_creation_input_tokens": 133}
}
```

This is the exact ADR-0028 success-shape the previous Handoff named.
Two independent things proved in one row:

- **ADR-0028 faithful reassembly is live.** `content` carries the
  thinking block (signature preserved via `signature_delta` even with
  empty `thinking_delta` stream) and the tool_use block with `input`
  as a *parsed dict* — `_finalize_input_json` ran the
  `input_json_delta` buffer through `json.loads` cleanly, no
  `_input_json_raw` fallback. Pre-ADR-0028 this row would have had
  `content: []`.
- **Option B (2026-05-14) is live on the same image.** All five
  SSE-derived columns the workstream targeted are populated:
  `model_served=claude-opus-4-7`, `input_tokens=6`, `output_tokens=152`,
  `cache_read_input_tokens=75512`, `cache_creation_input_tokens=133`,
  `stop_reason=tool_use`. The 2026-05-14 worklog's four-step recipe
  (deploy → `/admin/plugins` → real request → Supabase MCP check) is
  now satisfied end-to-end.

`keyword_block` also exercised in production: operator set
`LLMTRACK_KEYWORD_BLOCK_LIST = "no_response"` in `fly.toml` (was the
empty default), redeployed, and confirmed the plugin's
operator-configurable block path works. The setting is kept post-smoke
as the active live configuration — commit `8cd9566`.

Both 2026-05-14 and 2026-05-16 workstreams are **production-validated
as of this CP**.

## Handoff

CP commits, in order:

```
8138d91   server: faithful Anthropic response reassembly (ADR-0028)
c95e60c   docs: STATUS + worklog — ADR-0028 extractor faithful reassembly
8cd9566   infra: enable keyword_block on Fly (live config)
<this commit>   docs: STATUS + worklog — operator smoke closure
```

Smoke gate closed. Next blocking item moves to **ADR-#2 consent +
data-handling** — `analytics_sink` now stores full request + response
payloads (now demonstrably including tool_use `input` dicts), so any
external (non-team) testing requires this ADR before being safe to
enable. Operator-only use stays unblocked.

Queued follow-ups (none gating ADR-#2):

- **Pre-SSE upstream-failure-path row write** (ADR-0027 axis 2 impl).
  Today an upstream failure before the first SSE event yields no
  `public.exchanges` row at all; the open-INSERT happens after the
  bytes start flowing.
- **`exchanges.tool_call_count` fate.** Still at the `0` placeholder;
  derive via `jsonb_path_query` on `response_json.content` or
  deprecate / drop the column. Separate decision.
- **Response-side scrubbing.** Compatible with faithful reassembly
  (`extractor → scrubber → storage`); lands behind ADR-#2.
- **Backfill posture (unchanged).** Pre-`8138d91` `plugin_analytics`
  rows under a tool_use `stop_reason` carry `content: []`
  irrecoverably. Operator queries on historical rows must filter on
  `created_at >= <deploy_time_of_8138d91>`.
