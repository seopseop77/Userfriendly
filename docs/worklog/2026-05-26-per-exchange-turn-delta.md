# 2026-05-26 · ADR-0038 — per-exchange turn delta replaces conversation_messages

**Author**: Claude Code
**Session trigger**: Operator (verbatim, condensed): "메시지가 누적으로
들어가는 구조니까 굳이 conversation_messages 별도 테이블 없이
plugin_analytics에 exchange별 새로 추가된 input 한 개랑 응답을
저장하면 되지 않나? system은 변동 시에만 따로 기록. role도 turn_kind
대신 ADR-0037-derived 4-value(user_input/title_gen/tool_result/sidecar)로
가자. request_jsonb는 content만, wrapping 없이, session-opener wrapper도
스트립."
**Related docs**: ADR-0038 (this change), ADR-0036 (superseded),
ADR-0037 (superseded), prior worklog
`2026-05-26-display-role-vocab.md` (ADR-0037 closure + list-shape
title_gen regression fix).

## Interpretation

Operator wants the per-message dedup model retired in favour of
per-exchange turn deltas on `plugin_analytics`. Concrete shape
agreed during this session:

- Drop `conversation_messages`, `plugin_analytics_with_messages`
  view, `plugin_analytics.turn_kind`, `plugin_analytics.n_messages_at_request`.
- Add `plugin_analytics.role` (text, ADR-0037-derived 4 values:
  `user_input` / `title_gen` / `tool_result` / `sidecar`).
- Add `plugin_analytics.request_jsonb` (jsonb, content of
  `messages[-1]` with session-opener wrappers stripped; no
  `{role, content}` envelope — content only).
- Add `plugin_analytics.system_prompt_jsonb` (jsonb, populated only
  on the first exchange or when the request's system hash differs
  from the most recent non-null stored system in the conversation).
- Rename `response_json` → `response_jsonb` (and cast text → jsonb).
- `turn_seq` axis becomes `role IN ('user_input', 'tool_result')`
  rather than `turn_kind IN ('user_input_turn_start',
  'tool_continuation')` — same semantics, new vocab.
- Historic `system_prompt_jsonb` backfill **explicitly out of
  scope** — raw request bodies are not retained anywhere.

## What was done

- Wrote `docs/decisions/0038-per-exchange-turn-delta.md` with the
  full design, options considered, schema, forward-write flow,
  reconstruction queries, migration plan, and consequences. (commit
  &lt;pending&gt;)
- Marked `docs/decisions/0036-canonical-conversation-grouping.md`
  and `docs/decisions/0037-display-role-vocab-split.md` as
  `Superseded by ADR-0038`. (commit &lt;pending&gt;)

(Remaining items — code changes, alembic migration, tests,
live apply — staged in the task list and tracked under subsequent
checkpoints in this worklog.)

## Decisions

- **`tool_result` over `tool_continuation` for the role value.**
  Operator-chosen during the role-vocab debate this session.
  `tool_result` is content-shape descriptive (the message
  literally carries `tool_result` blocks), whereas
  `tool_continuation` was the request-level dynamic label in
  ADR-0036. Matching the vocab to content shape makes the role
  legible without referring back to request-level semantics.
- **`sidecar` over `framework_sidecar` for the catch-all role
  value.** Shorter, no extra noun stem; the contrast against
  `tool_result` already implies "not main flow."
- **Wrappers dropped at the storage boundary, not preserved
  anywhere.** Operator direction: the user-typed text is what
  matters for legibility; the wrappers are session-static framing
  duplicated against the system field and offer no analytical
  value. Retention would also require a separate column whose only
  consumer is rare debugging.
- **`response_jsonb` (jsonb-typed) replaces `response_json` (text).**
  Operator-confirmed both rename and type tightening. The cast is
  safe because the existing column stores raw JSON strings; the
  forward-write code path will start sending jsonb directly.

## What was done (continued)

- Rewrote
  `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/classifier.py`
  — dropped `TurnKind` Literal and the request-level `turn_kind`
  output; `classify_message` now emits the ADR-0038 4-value vocab
  (`user_input` / `title_gen` / `tool_result` / `sidecar`); added
  `extract_request_content` for wrapper-stripped `request_jsonb`
  payloads; `split_first_message` and the `_UPSERT_MESSAGE_SQL`
  surface removed. `_canonical_user_text` + `_SESSION_WRAP_RE`
  retained for `first_msg_hash`. (commit 121276a)
- Rewrote
  `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py`
  — removed `_upsert_messages`; INSERT now writes `role`,
  `request_jsonb`, `system_prompt_jsonb`; added `_resolve_system`
  (hash-compare against the conversation's most recent non-null
  `system_prompt_jsonb`, store on first exchange or on variation);
  renamed `response_json` → `response_jsonb` in the INSERT SQL.
  (commit 121276a)
- Added alembic migration
  `packages/llm_tracker_server/alembic/versions/0019_per_exchange_turn_delta.py`
  — adds the three new columns, casts + renames `response_json` →
  `response_jsonb` (text → jsonb), backfills `request_jsonb` +
  `role` from `conversation_messages` using a `CASE` mapper, drops
  `turn_kind` / `n_messages_at_request` columns, drops the helper
  view, drops the dedup table. (commit 121276a)
- Rewrote
  `packages/llm_tracker_plugin_analytics_sink/tests/test_classifier.py`
  and `tests/test_analytics_sink.py` for the new vocab + schema.
  53 pkg / 275 repo / ruff clean. (commit 121276a)
- **Applied the migration live via Supabase MCP** (`execute_sql`,
  single connection):
  - Phase 1 — `ADD COLUMN role / request_jsonb / system_prompt_jsonb`;
    `DROP VIEW plugin_analytics_with_messages`;
    `ALTER COLUMN response_json TYPE jsonb USING …`; `RENAME COLUMN
    response_json TO response_jsonb`.
  - Phase 2 — backfill `request_jsonb` + `role` from
    `conversation_messages` (one `UPDATE … FROM` with the CASE
    mapper baked into the migration script).
  - Phase 3 — `DROP COLUMN turn_kind`; `DROP COLUMN
    n_messages_at_request`; `DROP INDEX
    idx_conversation_messages_org_conv`; `DROP TABLE
    conversation_messages`; `UPDATE alembic_version SET version_num
    = '0019_per_exchange_turn_delta'`.

## Decisions (continued)

- **No new ADR for the historic system_prompt_jsonb gap.** Raw
  request bodies were never retained; the gap is explicit in the
  ADR-0038 consequences section. Forward writes start populating
  the column.
- **Backfill kept `turn_seq` values as-is.** ADR-0037-era rows that
  classified as `user_input_turn_start` but whose stored
  `messages[-1]` was a SUGGESTION MODE payload (e.g. exchange
  `01KSH2041NZYR0XA2NW46G1FRT` at 02:32:17) now classify as
  `sidecar` under ADR-0038's `classify_message`, yet retain a
  non-null `turn_seq` from the old vocab. Acceptable historic
  artefact — forward writes will produce consistent
  `(role, turn_seq)` pairs.

## Verification

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_analytics_sink/tests/ -q
================================ 53 passed in 0.34s ================================

$ .venv/bin/python3.12 -m pytest -q
================== 275 passed, 31 skipped in 6.40s ===================

$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_plugin_analytics_sink/
All checks passed!
```

Live data (post-migration):

```
plugin_analytics:
  total_rows                       16
  rows_with_role                   16  (0 missing)
  rows_with_request_jsonb          16  (0 missing)
  rows_with_system_prompt_jsonb     0  (expected — historic backfill out of scope)

role distribution:
  user_input    3
  title_gen     2
  tool_result   5
  sidecar       6

alembic_version:
  0019_per_exchange_turn_delta
```

Sample conv `01KSH1EK8JDG9RBWZZ8B38BZF9` reads top-to-bottom as
intended (user_input → tool_result → sidecar mix, all
`request_jsonb` payloads legible).

## What's left / known limits

- **Production plugin not yet redeployed.** The fly app
  `llm-tracker-server` is still running the ADR-0036 code path,
  which writes to `conversation_messages` (now dropped) and to
  `turn_kind` / `n_messages_at_request` (now dropped). Until the
  operator pushes + `fly deploy`s the new code, incoming exchanges
  will hit `analytics_sink.insert_failed` in structlog and produce
  no row. The proxy itself is unaffected (plugin failures are
  caught defensively in `on_persisted`).
- **`system_prompt_jsonb` will be NULL on all 16 historic rows
  forever.** Forward writes populate the column via
  `_resolve_system`'s variation tracker.
- **`turn_seq` mismatches with `role` on some historic rows.**
  Backfill did not recompute `turn_seq` (it was already populated
  by ADR-0036). Forward writes will produce consistent pairs.

## Handoff

ADR-0038 fully delivered and applied live. Next single step:
operator deploys the new plugin code to fly
(`llm-tracker-server`). Until then the production proxy keeps
forwarding but `analytics_sink` writes will fail — non-blocking
for end users but observable in logs.

After deploy, smoke-test by sending one exchange through the proxy
and confirming a row lands with the new columns populated.

## Follow-up · `x-anthropic-billing-header` stripping

**Trigger**: Operator pushed the new plugin code, ran a real
exchange, and noticed every exchange would store a fresh
`system_prompt_jsonb` (variation tracker firing on every write).
Root cause: Anthropic surfaces a per-request Claude Code telemetry
header inside the system field
(`x-anthropic-billing-header: cc_version=2.1.150; cc_entrypoint=cli;
cch=f5075;`). The `cc_version` and `cch` tokens drift between
otherwise-identical exchanges, so the previous hash compare —
which read raw text — saw "different system" on every call.

**Resolution (refinement of ADR-0038, not a new ADR)**: introduced
`classifier.normalize_system(system_field)` which drops text blocks
whose `text` starts with `x-anthropic-billing-header:`. The helper
is invoked by both `_system_hash` (so the variation hash ignores
the header drift) and `_resolve_system` (so the stored
`system_prompt_jsonb` already has the header stripped, preserving
the invariant *"same hash ⇒ identical stored bytes"*).

Scope kept tight: only the billing-header prefix is matched. A
generic `x-anthropic-*` strip was considered and rejected
(over-broad without a second concrete prefix to motivate it).

What changed:

- `classifier.py` — added `_SYSTEM_METADATA_PREFIXES` and
  `normalize_system(system_field) -> Any`. Idempotent: re-running
  on already-stripped output returns the same value.
- `plugin.py` — `_system_hash` and `_resolve_system` both pipe
  through `normalize_system`; `_resolve_system` now stores the
  normalized form rather than the raw `system_field`.
- `tests/test_classifier.py` — 7 new unit tests for
  `normalize_system` (strip / preserve / billing-header-only /
  string passthrough / None passthrough / cache_control preserved
  on kept blocks / idempotency).
- `tests/test_analytics_sink.py` — 2 new plugin-level tests
  (billing-header drift ⇒ `system_prompt_jsonb` NULL on second
  exchange; first-exchange stored form has the header dropped).
- `docs/decisions/0038-per-exchange-turn-delta.md` —
  §`system_prompt_jsonb semantics` and §Open questions updated.

No alembic migration: this is a code-only refinement. The 16
historic rows have `system_prompt_jsonb IS NULL` (raw bodies were
never retained), so the storage normalization applies only to
forward writes. ADR-0038's "Loses historic `system_prompt_jsonb`"
consequence is unchanged.

**Verification**:

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_analytics_sink/tests/ -q
================================ 62 passed in 0.43s ================================

$ .venv/bin/python3.12 -m pytest -q
================== 284 passed, 31 skipped in 6.45s ===================

$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_plugin_analytics_sink/
All checks passed!
```

(commit 00cc2b0)

## Suggestions (untouched)

- A `compact_resume` role value for the post-`/compact` resume
  marker (currently classifying as `sidecar`) could be carved out
  if usage justifies it later. Carried forward from the
  ADR-0037 worklog's open suggestion.

## Suggestions (untouched)

- A `compact_resume` role value for the post-`/compact` resume
  marker (currently classifying as `sidecar`) could be carved out
  if usage justifies it later. Carried forward from the
  ADR-0037 worklog's open suggestion.
