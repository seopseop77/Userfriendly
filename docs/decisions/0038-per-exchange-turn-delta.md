# ADR-0038 · Per-exchange turn delta on plugin_analytics; conversation_messages retired

- **Status**: Proposed
- **Date**: 2026-05-26
- **Author**: Claude Code (operator-directed)
- **Related**:
  - Worklog: `docs/worklog/2026-05-26-per-exchange-turn-delta.md`
  - **Supersedes** ADR-0036 (canonical conversation grouping; per-message
    dedup table + helper view + `n_messages_at_request` pointer).
  - **Supersedes** ADR-0037 (display role vocab on
    `conversation_messages.role`).
  - Touches public interfaces per CLAUDE.md §9: drops the
    `conversation_messages` table, drops the
    `plugin_analytics_with_messages` view, drops `turn_kind` and
    `n_messages_at_request` columns on `plugin_analytics`, renames
    `response_json` → `response_jsonb`, and adds three new columns
    (`role`, `request_jsonb`, `system_prompt_jsonb`).

## Context

ADR-0036 stored every Anthropic Messages API message as its own
`conversation_messages` row keyed by `(conversation_id, msg_index)`,
with `plugin_analytics.n_messages_at_request` pointing into the
table so a helper view could re-materialise the `messages[]` array
visible to any exchange. ADR-0037 layered a 5-role display vocab
(`system_prompt`, `user_input`, `title_gen`, `model_output`,
`assistant`) onto `conversation_messages.role`, adding a row-split
rule for the session-opener and a priority UPSERT for the
title-gen sidecar.

Two surface signals in 2026-05-26 reframed the design:

1. **The per-message attribute we keep adding is fragile.** ADR-0037's
   `role` required two classifiers (`classify_message` +
   `split_first_message`), a session-shape regex with several
   special cases, a sidecar UPSERT WHERE clause, and an in-place
   split of the first message into two rows. A list-shape title-gen
   sidecar was misclassified on the first new write after deploy
   (conv `01KSGW0CHY3HAFEM4QRRJ3Y1ST`, commit `937f6d1` fixed it).
   The complexity is concentrated on what is essentially a label
   the exchange layer already carries as `plugin_analytics.turn_kind`.

2. **Anthropic Messages API has an A/B/A/B/… structure.** Each
   exchange resends every prior message, so per-message dedup is one
   way to avoid duplication. Storing each exchange's *delta* (the
   new user-side message plus the model's response) avoids the
   duplication just as well with a simpler model: `messages[]`
   visible to any past exchange is reconstructed by stitching the
   conversation's exchange deltas in chronological order, instead of
   indexing into a separately-keyed dedup table.

## Options considered

1. **Status quo (ADR-0036 + ADR-0037).** Keep the per-message table
   and the helper view. Rejected — the complexity cost recurs on
   every future per-message attribute.

2. **Per-exchange turn delta on `plugin_analytics` (chosen).** Move
   the message data onto the exchange row; collapse the per-message
   classifier into one role label per exchange; drop the dedup
   table and helper view.

3. **Per-exchange turn delta but store `system` on every row.** Skip
   variation-tracking. Rejected per operator preference — the
   conversation-grouping invariant ("`first_msg_hash` defines the
   conversation") makes variation-tracking legible and avoids
   storage churn from repeated near-identical CLAUDE.md payloads.

4. **Per-exchange turn delta + include `system` in `first_msg_hash`
   to make "one conversation = one system" an invariant.** Rejected
   because the dynamic components of Claude Code's system
   (date, working dir, git status, recent commits, cache_control
   breakpoint position) would fragment a single user-perceived
   conversation into many DB-level conversations.

## Decision

**Pick option 2.** Per-exchange turn delta on `plugin_analytics`.

### Schema

`plugin_analytics` gains three new columns, renames one, and drops
two:

```sql
ALTER TABLE plugin_analytics
    -- New: ADR-0037-derived per-row role label.
    ADD COLUMN role                 text,
    -- New: this exchange's user-side delta (content only).
    ADD COLUMN request_jsonb        jsonb,
    -- New: system field, populated only when it differs from the
    -- previous non-null system in this conversation.
    ADD COLUMN system_prompt_jsonb  jsonb;

-- Type tightened from text to jsonb, with a name swap.
ALTER TABLE plugin_analytics
    ALTER COLUMN response_json TYPE jsonb USING response_json::jsonb;
ALTER TABLE plugin_analytics
    RENAME COLUMN response_json TO response_jsonb;

-- Drops (after backfill — see Migration below).
ALTER TABLE plugin_analytics
    DROP COLUMN turn_kind,
    DROP COLUMN n_messages_at_request;

DROP VIEW  plugin_analytics_with_messages;
DROP TABLE conversation_messages;
```

### `role` vocab (4 values, replaces `turn_kind`)

| value | content shape | flow | turn_seq axis |
|---|---|---|---|
| `user_input` | user's typed text; on the session-opener this is the user-typed text **after wrapper stripping** (see below) | main | **yes** |
| `title_gen` | `<session>...</session>` payload, as a bare string or a single-block list | sidecar | no (NULL) |
| `tool_result` | block list containing one or more `{type:"tool_result", ...}` blocks (Claude Code's response to the model's prior `tool_use`) | main | **yes** |
| `sidecar` | every other framework-synthesised `role=user` message: `/compact` summarize, `[SUGGESTION MODE: ...]`, step-away recap, post-`/compact` resume marker, any `messages[-1]` whose only text blocks are synthetic wrappers | sidecar | no (NULL) |

ADR-0037's `system_prompt` is not a `role` value here — system data
lives in its own column. ADR-0037's `model_output` is not a `role`
value either — the model's response is always on the same row as
its driving request, in `response_jsonb`.

ADR-0037's `assistant` bucket splits into `tool_result` and
`sidecar` so main-flow continuations and out-of-band sidecars are
distinguishable from the row alone, with no content-shape filter
needed at query time.

### `request_jsonb` semantics

Holds the **content of `messages[-1]`** for this request — i.e. the
last user-side message in the API request. The wrapping `{"role":
"user", "content": ...}` envelope is not stored; only the content
(string or block list). Role information lives in the new `role`
column.

**Session-opener wrapper stripping.** On the conversation's first
exchange (the only place Claude Code prepends `<system-reminder>` /
`<command-*>` / `<local-command-*>` blocks before the user's typed
text), the wrapper blocks are dropped from `request_jsonb`:

- If exactly one non-wrapper block remains and it is a bare
  `{type:"text",text:"..."}`, store the inner text as a bare string.
- If multiple non-wrapper blocks remain (rare — `/clear` and
  `/compact` follow-up shapes), store them as a list.
- If only wrapper blocks exist (e.g. post-`/compact` resume marker
  alone), the message classifies as `sidecar` and the wrapper list
  is stored as-is — the row is informational, not user input.

The wrappers themselves are not retained anywhere; raw bodies are
not preserved in any table, and the wrapper text is mostly
session-static framing already redundant with the `system` field.

**Framework auto-call prompts treated as wrappers (2026-05-26 refinement).**
Claude Code internally issues some LLM calls without the user typing
a message — currently observed: the WebSearch trigger ("Perform a
web search for the query: …") and the PreCompact summarization
prompt ("CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.…").
These prompts arrive as plain text blocks (no `<tag>` wrapper),
which made them indistinguishable from user-typed text under the
original wrapper-prefix list and caused them to classify as
`user_input`. The two known prefixes are added to the wrapper set
so that:

- A turn whose only non-wrapper text is the framework prompt
  classifies as `sidecar` (wrapper-only payload).
- A turn where the framework prompt accompanies real user text
  stays `user_input`; the framework prompt is stripped from
  `request_jsonb` and the user text survives.

This is whack-a-mole by design: new framework prompts get added
as they are discovered. A more robust signal (e.g. inspecting
`request.tools` for `web_search_*` server tools, or detecting the
distinct `system_prompt` Claude Code emits for these calls) is
deferred until a third pattern motivates the work.

**Non-opener exchanges.** `request_jsonb` is `messages[-1].content`
verbatim — no normalisation (Rule A / Rule B are retired).

### `system_prompt_jsonb` semantics

Verbatim `request.system` (string or list of `{type:"text", ...}`
blocks). Stored only when:

- This is the first exchange in the conversation (no previous row
  with a non-null `system_prompt_jsonb`), OR
- The current request's `system` hash differs from the most recent
  non-null `system_prompt_jsonb` in this conversation.

The variation-tracking hash is SHA-256[:16] of `_system_text(request)`
**after dropping two classes of noise**:

- `cache_control` keys on system text blocks (prompt-caching
  artefact; same spirit as ADR-0036 Rule A but applied to `system`).
- Entire text blocks whose `text` starts with
  `x-anthropic-billing-header:`. Anthropic surfaces a per-request
  Claude Code telemetry header
  (`cc_version=2.1.150; cc_entrypoint=cli; cch=f5075;` and similar)
  inside the system field. The `cc_version` and `cch` tokens drift
  across exchanges without carrying any system-instruction content,
  so leaving them in would make the variation tracker fire on
  essentially every exchange.

The same stripping is applied **at storage time**: `system_prompt_jsonb`
stores the post-strip system, not the raw one. This preserves the
invariant *"if two exchanges hash equal, their stored
`system_prompt_jsonb` payloads are byte-identical."* Without it, a
future hash compare against a previously-stored row could disagree
with a hash compare against the raw request payload.

Implementation lives in `classifier.normalize_system(system_field)`
and is shared by `_system_hash` and `_resolve_system` in the plugin
module.

### `turn_seq`

Definition update: `turn_seq` is `MAX(turn_seq) + 1` over rows in
the same conversation **where `role IN ('user_input', 'tool_result')`**.
Other roles stay NULL. Same cumulative-counter semantics as
ADR-0036, with `tool_result` taking the place of `tool_continuation`
and `user_input` taking the place of `user_input_turn_start`.

### Forward-write flow

1. Run `classify_request` — now produces `first_msg_hash`,
   `slash_commands`, `n_messages` (used only for the chain-lookup
   decision; not stored). `turn_kind` is no longer emitted.
2. Resolve `(conversation_id, prev_row)` via the (B) chain-lookup
   on `first_msg_hash` (unchanged).
3. Classify `messages[-1]` with the new 4-value `classify_message`.
   Compute `role`.
4. Compute `request_jsonb`:
   - If `role == 'user_input'` and this is the conversation's first
     exchange (or the message has leading wrapper blocks), strip
     wrappers per the rules above.
   - Otherwise, store `messages[-1].content` verbatim.
5. Compute `system_prompt_jsonb`:
   - Hash this request's `system` (with cache_control stripped).
   - Compare to most recent non-null `system_prompt_jsonb` in this
     conversation (org-scoped); store verbatim system iff different
     or absent; else NULL.
6. Compute `turn_seq` per the updated definition.
7. INSERT the analytics row with all of the above + the existing
   metadata columns + `response_jsonb`.

No conversation_messages writes. No UPSERT path. No
`_upsert_messages`. No helper view dependency.

### Reconstruction queries

**Messages[] visible to exchange `E` in conversation `C`** (main
flow only — sidecars excluded by design):

```sql
SELECT role, request_jsonb, response_jsonb
FROM plugin_analytics
WHERE conversation_id = C
  AND created_at <= E.created_at
  AND role IN ('user_input', 'tool_result')
ORDER BY created_at;
```

Unfold each row into two messages: `{role: "user", content:
request_jsonb}` (or just the bare string for `user_input` after
wrapper stripping) followed by `{role: "assistant", content:
response_jsonb.content}`. The result reproduces the API
`messages[]` array.

**System visible to `E`**:

```sql
SELECT system_prompt_jsonb FROM plugin_analytics
WHERE conversation_id = C
  AND created_at <= E.created_at
  AND system_prompt_jsonb IS NOT NULL
ORDER BY created_at DESC LIMIT 1;
```

**Sidecars for `C`** (debugging the framework's out-of-band calls):

```sql
SELECT role, request_jsonb, response_jsonb FROM plugin_analytics
WHERE conversation_id = C AND role IN ('title_gen', 'sidecar')
ORDER BY created_at;
```

### Migration

Alembic migration is a single revision:

1. **Add new columns** (nullable): `role`, `request_jsonb`,
   `system_prompt_jsonb`.
2. **Cast and rename**: `response_json` → `response_jsonb` (text →
   jsonb via `USING response_json::jsonb`).
3. **Backfill `request_jsonb` and `role` from `conversation_messages`**:
   for each `plugin_analytics` row, look up the conversation_messages
   row at `msg_index = n_messages_at_request - 1` (the API
   `messages[-1]`). Copy `content_jsonb` → `request_jsonb`. Map the
   ADR-0037 role to the ADR-0038 vocab:
   - `user_input` → `user_input`
   - `title_gen` → `title_gen`
   - `model_output` → impossible at messages[-1] (assistant is never
     last on a user request); ignore.
   - `assistant` with tool_result blocks in content_jsonb → `tool_result`
   - `assistant` otherwise → `sidecar`
   - (`system_prompt` role rows are not at messages[-1] either —
     skipped; their wrappers are dropped per ADR-0038's strip rule.)
4. **`system_prompt_jsonb` is not backfilled** — raw request bodies
   are not retained anywhere, so all historic rows keep NULL.
   Forward writes from this deploy onward carry the variation-tracked
   system.
5. **Drops**: `turn_kind`, `n_messages_at_request` columns; the
   `plugin_analytics_with_messages` view; the `conversation_messages`
   table.

The single-revision approach is acceptable here because the
production data volume is small (≈ 7 conversations, ≈ 30
exchanges as of 2026-05-26). For larger systems this would split
into two revisions (add columns + backfill in one; drop after a
live deploy verifies in the second).

## Consequences

- **Drops a large attribute surface**: `classify_message` shrinks
  to a 4-value classifier (no split logic), `split_first_message`
  removed, `_UPSERT_MESSAGE_SQL` removed, `_upsert_messages`
  removed, ADR-0036 helper view removed, `n_messages_at_request`
  pointer removed, Rule A / Rule B `canonical_message` removed.
  `_canonical_user_text` survives for `first_msg_hash` only.
- **Main-flow vs sidecar visible from `role` alone.** No
  content-shape SQL filter needed; `role IN (...)` is enough.
- **`response_jsonb` is now jsonb-typed.** Downstream SQL that
  cast `response_json` to jsonb at query time can drop the cast.
- **`request_jsonb` legibility**: a top-to-bottom read of
  `plugin_analytics` rows in a conversation reads as `["뭐하냐",
  assistant_reply, "calculator.py 만들어봐", thinking_plus_tool_use,
  tool_result, …]` — exactly what the model saw, with no wrapper
  pollution.
- **Per-message attribute extensibility goes away.** A future
  requirement like "tag each block with which scrub rule fired"
  must live inside `request_jsonb` (as JSONB structure) or in a new
  sibling table. Acceptable — no concrete near-term per-message
  attribute use case.
- **Loses historic `system_prompt_jsonb` for ≈ 272 prior rows.**
  Raw bodies were never retained; backfill is impossible. Forward
  writes restore the data.
- **Reversibility**: medium. The column-add + rename is trivially
  reversible. The conversation_messages drop is reversible by
  re-deriving from `request_jsonb` + `response_jsonb` per row, but
  loses the dedup property — re-introducing dedup would require
  re-deriving `msg_index` and re-running ADR-0036's deduplication.
  Treat the drop as one-way.

## Open questions

- **Session-opener `request_jsonb` shape with `/clear` or `/compact`
  command markers.** When the user types `/clear` or `/compact`,
  Claude Code injects `<command-name>/clear</command-name>` plus
  follow-up wrappers around any trailing user text. The stripper
  drops the command-name block (classified as a wrapper); the
  trailing user text survives. If the user types just `/clear` with
  no follow-up, only wrapper blocks remain → row classifies as
  `sidecar`. Verify in live data once forward writes resume.
- **System-variation false positives from `cache_control` movement.**
  The hash compare drops `cache_control` keys (implicitly, by
  extracting only `text`) and `x-anthropic-billing-header:` blocks
  (explicitly, via `normalize_system`). If any other prompt-caching
  artefact or Anthropic-injected metadata drifts independently of
  meaningful content, the variation tracker will over-trigger.
  Monitor with a query that counts `system_prompt_jsonb IS NOT
  NULL` rows per conversation against an expected baseline.
