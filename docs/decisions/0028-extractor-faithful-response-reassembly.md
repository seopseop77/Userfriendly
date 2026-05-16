# ADR-0028 · Extractor `response_json`: faithful reassembly, not curated summary

- **Status**: Accepted
- **Date**: 2026-05-16
- **Author**: Claude Cowork (decision) / Claude Code (drafting)
- **Related**: ADR-0026 (HookContext response accessors — defines the surface),
  ADR-0027 (close-out policy — defines NULL semantics for summary columns),
  `docs/worklog/2026-05-16-extractor-faithful-response.md`
- **Extends**: ADR-0026 (tightens the `response_content_json()` contract)

## Context

ADR-0026 introduced `HookContext.response_content_json()` as the canonical handle
plugins use to read the model's response. The extractor producing it
(`extractors/anthropic.py`) shipped under ADR-0026 with `text_delta` handling
only; tool-use blocks were flagged as "not yet extracted" in the module
docstring.

The user's first production run surfaced the natural consequence: a request that
ended with `stop_reason: "tool_use"` and `output_tokens: 112` was stored with
`response_json.content = []`. The model emitted 112 tokens of tool-use payload
(id, name, input), the proxy forwarded those bytes intact (Claude Code received
them and invoked the tool), but the durable analytics row carries an empty
shape — visually indistinguishable from "the model said nothing."

Two interpretations of what `response_json` *should* be:

- **A. Curated summary.** Extract the fields the central server has a use for
  (text content + token usage). Each new block type (`tool_use`, `thinking`,
  `server_tool_use`, …) requires an extractor change per type. An empty
  `content` on a row means "we chose not to extract this," not "the model
  produced nothing."
- **B. Faithful reassembly.** Extract every block the model emitted, regardless
  of type. New block types are preserved best-effort without requiring a server
  change. An empty `content` on a row means the model genuinely produced no
  content.

The same data structure cannot service both intents cleanly. The column name
(`response_json`) and accessor (`response_content_json()`) both advertise B,
but the implementation today delivers A.

## Options considered

1. **Option A — Stay curated; document the gaps.** Add per-type extractor
   branches as needed (`tool_use` this round, `thinking` next, …).
   *Pros*: smallest diff today. *Cons*: every new Anthropic block type forces a
   server change; data loss is invisible (no marker on the row indicates a
   block was dropped); the column name keeps lying about what it stores.
2. **Option B — Faithful reassembly is the contract.** The extractor's job is
   "reproduce Anthropic's non-stream response shape." All `content_block_*`
   events accumulate into the block list; unknown delta types are preserved
   fail-open under `_extra_deltas`. Summary columns (`output_tokens`,
   `model_served`, …) remain a parallel output drawn from the same parse.
   *Pros*: forward-compatible; the column name keeps its promise; analytics
   derive from the canonical body. *Cons*: schema is now Anthropic-shaped
   (we follow upstream verbatim, including block types we don't understand).

## Decision

**Pick Option B — faithful reassembly.** Three reasons:

1. **Storage is canonical; analysis is derived.** This matches what the project
   already does for `messages_json` (we store the request body as-sent, not a
   normalized projection). Counting tool calls, "did this request invoke
   tool X," etc. are downstream-of-storage queries — one `jsonb_path_query`
   each. Curated columns duplicate the source.
2. **Forward-compatibility is cheap when we don't curate.** A new Anthropic
   block type (`thinking` has landed; `server_tool_use` is on the horizon)
   costs zero server changes to *store* under Option B. The block is captured
   as the extractor sees it. Curated extraction can opt in later for fields
   the server needs to surface specifically.
3. **The column name has to keep its promise.** `response_json` empty when the
   model issued tool calls is a quiet integrity failure — every downstream
   analysis inherits it, and the failure is silent. Fixing the contract now is
   cheaper than discovering it during the consent + data-handling ADR review.

### Extractor responsibilities (refined contract)

- **`content_block_start`** — seed `blocks[index]` from the event's
  `content_block` payload as-is (shallow copy). No type filtering. The block
  carries whatever fields Anthropic set at start (`type`, `id`, `name`,
  initial `text=""`, initial `input={}`, etc.).
- **`content_block_delta`** — dispatch by `delta.type`:
  - `text_delta` → `blocks[index]["text"] += delta["text"]`
  - `input_json_delta` → buffer `partial_json` per index
  - `thinking_delta` → `blocks[index]["thinking"] += delta["thinking"]`
  - `signature_delta` → `blocks[index]["signature"] += delta["signature"]`
  - **Anything else** → `blocks[index].setdefault("_extra_deltas",
    []).append(delta)`. Forward-compatibility lever; future ADRs can promote
    a specific delta type to a typed field once Anthropic stabilizes it.
- **`content_block_stop`** — if a `partial_json` buffer exists for the index,
  `json.loads` it into `block["input"]`. On parse failure: store the raw
  string at `block["_input_json_raw"]` (fail-open: no data dropped).
- **`message_start`** / **`message_delta`** — unchanged: feed `ResponseUsage`
  (the parallel summary).

### Final response assembly

`response_json` is `json.dumps` of:

```json
{
  "model": "<model_served>",
  "content": [<blocks[i] for i in sorted(blocks)>],
  "stop_reason": "<stop_reason>",
  "usage": {
    "input_tokens": ...,
    "output_tokens": ...,
    "cache_read_input_tokens": ...,
    "cache_creation_input_tokens": ...
  }
}
```

The shape mirrors what Anthropic returns on the non-stream Messages API.
Plugins can pass it through `anthropic.types.Message.model_validate` for typed
access or treat fields as plain dicts.

### Non-goals

- **Per-block type-narrowing.** The extractor does not validate that a
  `content_block_start` for `tool_use` carries `id` and `name`; whatever
  Anthropic put there is preserved. Validators belong in analysis code.
- **`tool_calls` table population.** `public.tool_calls` exists in the schema
  but no code path writes it. Whether it survives or is dropped is a separate
  decision.
- **`exchanges.tool_call_count`.** Stays at 0. Deriving the count from
  `response_json.content` is one SQL expression; a precomputed column
  duplicates the source. The column's fate (deprecate / drop / leave) is a
  separate decision.

## Consequences

- **Enables**: faithful storage of `tool_use`, `thinking`, `signature`, and
  future block types; one source of truth for any analytics built on response
  shape; consistent meaning of `response_json` across all `plugin_analytics`
  rows.
- **Forecloses**: the interpretation that `response_json` is a
  curated / scrubbed projection. If a future privacy ADR requires response-side
  scrubbing, that becomes a separate post-extractor scrubber pass (mirrors the
  request-side scrubber design from Phase 1c) — not divergence inside the
  extractor itself.
- **Reversibility**: high. Tightening back to curated is a single-file edit;
  the public surface (`response_content_json()`) is unchanged.
- **Backfill**: historical rows with `content: []` under a tool-use
  `stop_reason` are not backfillable — we did not store the upstream bytes.
  Operator analytics on past rows must filter
  `WHERE created_at >= <deploy_time_of_this_change>`.

## Open questions

- **Privacy / scrubbing of response bodies.** The user's request body and the
  model's response are both stored at L3 (raw) in `plugin_analytics`. The
  consent + data-handling ADR (still pending; STATUS.md "ADR-#2") will likely
  require scrubbing primitives on this path. Faithful reassembly is compatible
  with a downstream scrubber pass; the order becomes
  `extractor → scrubber → storage` once the scrubber lands.

## Settles

The "tool-use blocks are not yet extracted" caveat in the extractor docstring
(introduced under ADR-0026 checkpoint β). After this ADR the extractor's
contract is "faithful reassembly," not "extract what we currently use."
