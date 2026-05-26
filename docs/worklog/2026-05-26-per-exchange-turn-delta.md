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

## Verification

(To be filled at the next checkpoint, after code changes + tests +
live migration land.)

## What's left / known limits

- **Phase A — code/migration/tests**: rewrite `classifier.py` (drop
  `turn_kind` output, ADR-0038 4-value `classify_message`,
  wrapper-stripping helper for the session-opener), retire
  `normalize.py`'s `canonical_message` (keep
  `_canonical_user_text` for `first_msg_hash`), rewrite
  `plugin.py` (no `_UPSERT_MESSAGE_SQL`, write role / request_jsonb
  / system_prompt_jsonb on INSERT, system-variation hash compare
  with cache_control stripping). Add alembic revision. Update unit
  tests for new vocab + schema.
- **Phase B — live apply**: run migration on Supabase; backfill
  `request_jsonb` + `role` from `conversation_messages`; verify
  row counts match expected; drop the now-empty
  `conversation_messages` table and `plugin_analytics_with_messages`
  view.
- **Phase C — finalisation**: STATUS.md + worklog Handoff + Status
  hash backfill commit.

## Handoff

(Will be set at end of session.)

## Suggestions (untouched)

- A `compact_resume` role value for the post-`/compact` resume
  marker (currently classifying as `sidecar`) could be carved out
  if usage justifies it later. Carried forward from the
  ADR-0037 worklog's open suggestion.
