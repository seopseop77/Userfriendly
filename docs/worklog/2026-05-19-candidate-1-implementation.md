# 2026-05-19 · Candidate-1 implementation (conversation_messages dedup)

**Author**: Claude Code
**Session trigger**: "docs/worklog/2026-05-19-candidate-1-handoff.md
읽고 후보 1 구현 시작해."
**Related docs**:
- Handoff doc — `docs/worklog/2026-05-19-candidate-1-handoff.md`
- ADR — `docs/decisions/0032-conversation-messages-dedup.md`
- Prior tracks — `docs/worklog/2026-05-19-scrubber-json-aware-and-b-rule.md`

## Interpretation

The handoff doc spec'd every byte of the change in advance. This session
executes §11 steps 1–3 (open ADR + implement code + tests green) and
stops short of steps 4–8 (live Supabase migration apply, backfill,
`messages_json` column drop, `fly deploy`) — those touch live data /
running image and need operator confirmation before they fire.

## What was done

- Created `docs/decisions/0032-conversation-messages-dedup.md` — ADR
  accepting Candidate 1 over Candidate 2 (idempotency + the
  normalization spec is already nailed).
- Created `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/normalize.py`
  — `canonical_message()` applies Rule A (drop `cache_control` on every
  block) + Rule B (collapse single bare-text-block array to bare
  string). Both rules derived empirically from the 2026-05-19 STRESS run.
- Created `packages/llm_tracker_plugin_analytics_sink/tests/test_normalize.py`
  — 8 unit tests covering the rules + the verified-stable fields
  (`tool_use.id`, `tool_result.tool_use_id`, thinking `signature`).
- Created `packages/llm_tracker_server/alembic/versions/0015_conversation_messages.py`
  — adds `conversation_messages` table, `plugin_analytics.n_messages_at_request`
  column, and `plugin_analytics_with_messages` view.
  **Intentionally does NOT drop `messages_json` in the migration body**
  — the column drop runs as a follow-up step after the live backfill
  is verified (§6 V1–V5 of the handoff). Splitting the drop out means
  an interrupted backfill cannot leave the row pointer without the
  source data.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/storage/models.py`
  — added `ConversationMessage` ORM mirroring migration 0015 columns +
  index. (`PluginAnalytics` is migration-only, not an ORM class, so no
  changes there.)
- Modified `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py`
  — `_INSERT_SQL` swaps `messages_json` for `n_messages_at_request`;
  new `_UPSERT_MESSAGE_SQL` constant; `on_persisted` runs N per-message
  UPSERTs (with `canonical_message()` normalisation) before the
  analytics-row INSERT, both inside the existing `engine.begin()`
  transaction.
- Modified `packages/llm_tracker_plugin_analytics_sink/tests/test_analytics_sink.py`
  — `_insert_params` re-anchored to the `n_messages_at_request` key;
  new `_upsert_calls` helper; existing happy-path / null-response /
  fallback-recovery tests adjusted; two new tests
  (`test_messages_upserted_one_per_index`,
  `test_normalization_applied_at_upsert_boundary`).

## Decisions

- **Column drop deferred out of the migration body.** The handoff §5
  shows backfill happening as a step *between* "create table+column"
  and "drop column", and §11 step 6 explicitly drops via a follow-up.
  Cleanly separating the schema-extending DDL (this migration) from
  the destructive DDL (drop) is the only way to make the operation
  resumable if the backfill is interrupted.
- **Backfill chosen as Python-via-asyncpg, not SQL.** Per handoff §8 R3
  — keeps the normalization rule single-sourced through
  `canonical_message()`. Will materialise the script in the next
  session's worklog when the apply happens.
- **Per-message UPSERT runs before the analytics-row INSERT.** Same
  transaction; the helper view filters `msg_index < n_messages_at_request`
  so a row visible without its messages would be broken.
- **`PluginAnalytics` is not an ORM class.** The handoff mentioned an
  ORM column change but the actual ORM file
  (`storage/models.py`) only has `Exchange`, `AuditLog`, `Org`,
  `ApiToken`. No ORM modification needed beyond adding
  `ConversationMessage`.

## Verification

```
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_sdk \
    packages/llm_tracker_plugin_analytics_sink \
    packages/llm_tracker_server -q
157 passed, 18 skipped in 5.57s

$ .venv/bin/python3.12 -m ruff check packages/
All checks passed!

$ cd packages/llm_tracker_server && ../../.venv/bin/python3.12 \
    -m alembic upgrade --sql 0014_analytics_turn_class:0015_conversation_messages
# clean BEGIN ... COMMIT block; CREATE TABLE + ADD COLUMN + CREATE VIEW
# + UPDATE alembic_version, all atomic.

$ ../../.venv/bin/python3.12 \
    -m alembic downgrade --sql 0015_conversation_messages:0014_analytics_turn_class
# clean reverse; DROP VIEW + DROP COLUMN + DROP TABLE + ADD COLUMN
# messages_json (nullable text, no data restore).
```

Test count baseline: was 147 passed + 18 skipped at the prior commit
`748e62f`; this session adds 8 normalize tests + 2 plugin tests =
157 passed (+10), 18 skipped (unchanged). Matches the §10 expected
`~155 passed (+ 8 new normalize tests, +2-3 plugin tests)` posture.

## What's left / known limits

- **Live migration apply** (handoff §11 step 3) — pending operator
  confirmation. Will run as one atomic `BEGIN; ... COMMIT;` block via
  Supabase MCP `execute_sql`, matching the 0013 / 0014 precedent.
- **Backfill script** (§11 step 4) — pending. Will be a one-off
  asyncpg script that imports `canonical_message` and walks
  `plugin_analytics` rows once. The script lives inline in the
  next-session worklog (per handoff §5 it is not shipped in the tree).
- **Verification queries V1–V5** (§11 step 5) — pending; runs after
  backfill against live data.
- **`messages_json` column drop** (§11 step 6) — pending; runs after
  V1–V5 pass.
- **`fly deploy`** (§11 step 7) — operator-owned, fires after the drop.
- **Post-deploy smoke** (§11 step 8) — single proxy hit to confirm
  the new write path produces a fresh `conversation_messages` row +
  a `plugin_analytics` row with `n_messages_at_request` set.

## Handoff

Code half is committed and ready for the live apply sequence. Next
session resumes at handoff §11 step 3:

1. Apply migration 0015 to Supabase via MCP `execute_sql`.
2. Run the backfill Python script (asyncpg + `canonical_message`).
3. Verify §6 V1–V5 against the STRESS conv
   (`01KS084X32YARSRKGBY35ACRYM`).
4. Drop `plugin_analytics.messages_json`.
5. Operator runs `fly deploy`.
6. Single-prompt post-deploy smoke.

## Suggestions (untouched)

- None this session.
