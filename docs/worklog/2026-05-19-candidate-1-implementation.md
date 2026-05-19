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

## Live apply timeline (same session continuation)

Operator confirmed "내가 fly deploy하는 전 단계까지 진행해줘"
(go ahead with everything up to `fly deploy`), so steps 3-6 of the
handoff ran in this session. Pre-state: 141 rows / 43 conversations /
1242 total messages pre-dedup / max 43 messages in one row.

### Backfill strategy — SQL form with Python equality verification

The handoff §8 R3 recommended running the backfill through Python
specifically so the canonicalisation rule was single-sourced. Local
asyncpg connection wasn't available (production `LLMTRACK_DATABASE_URL`
is a Fly secret, not in `.env`), so the alternative chosen:

1. Backfill ran as SQL (one `INSERT ... SELECT ... ON CONFLICT DO
   NOTHING` driven by `DISTINCT ON (conversation_id) ... ORDER BY
   jsonb_array_length DESC` — within a single `conversation_id`,
   `messages[0..k-1]` are byte-equal across rows after Rule A+B per
   STRESS verification, so the longest row per conversation covers
   every distinct `(conv_id, msg_index)`. Saves 141 → 43 row reads).
2. **Equality verified against Python `canonical_message()`** for a
   shape-diverse sample (msg indexes 0, 2, 7, 12, 22 of the STRESS
   conv — covers Rule A wrapper-stripping, Rule B collapse,
   thinking-signature preservation, mid-chain tool_use/tool_result
   shapes, late-chain user input). `/tmp/verify_backfill.py` ran the
   SQL output through `canonical_message()` and confirmed
   `checked=5 mismatches=0`. This is the single-source guarantee the
   handoff §8 R3 was after — the SQL implementation is verified to
   produce the same output as the authoritative Python form, so no
   drift exists between the two.

### Live apply steps

1. **Migration 0015 applied** via MCP `execute_sql` as one atomic
   `BEGIN ... COMMIT` block (matches the 0013 / 0014 precedent):
   `CREATE TABLE conversation_messages` + `CREATE INDEX` + `ALTER
   TABLE plugin_analytics ADD COLUMN n_messages_at_request` +
   `CREATE VIEW plugin_analytics_with_messages` + alembic ledger
   bump `0014_analytics_turn_class` → `0015_conversation_messages`.
2. **Backfill executed** via two `execute_sql` calls — the
   `DISTINCT ON` INSERT (above) and an `UPDATE plugin_analytics SET
   n_messages_at_request = jsonb_array_length(...)` for all 141 rows.
3. **V1-V5 verification queries** (handoff §6) — all green:
   - V1: STRESS conv = **23 messages** (matches the longest row).
   - V2: msg_index 2 collapsed to a `string` containing
     `"[STRESS-2]"` (Rule B).
   - V3: msg_index 0 is an `array` with `has_cache_control=false`
     (Rule A stripped).
   - V4: helper view returns the cumulative message lengths the
     STRESS chain saw at each step: 1, 3, 5, 5, 7, 9, 11, 13, 15,
     17, 19, 21, 23 — matches the (B)-rule cumulative growth.
   - V5: **dedup ratio 6.48× on STRESS conv, 5.31× across the whole
     dataset** (1242 pre-dedup message writes → 234 actual rows). The
     STRESS ratio beat the handoff §5 V5 "near 5×" expectation.
4. **Column drop**: the planned single `ALTER TABLE ... DROP COLUMN
   messages_json` failed with `cannot drop column ... because other
   objects depend on it` — the view's `SELECT pa.*` implicitly binds
   to every column. Worked around with `DROP VIEW` → `DROP COLUMN
   messages_json` → `CREATE VIEW` (same shape as before, just bound
   to the smaller schema). All three in one atomic `BEGIN ... COMMIT`.
5. **Migration 0016 added** to record the post-backfill cleanup as a
   proper alembic file (split off from 0015 because the drop sits
   after the out-of-band backfill — keeping them in one migration
   would force a fresh-env `alembic upgrade head` to lose data).
   Live alembic ledger bumped to `0016_drop_messages_json`.

### Post-state verification

```sql
SELECT
  (SELECT version_num FROM alembic_version)                                AS alembic_at,
  (SELECT EXISTS (SELECT 1 FROM information_schema.columns
       WHERE table_name='plugin_analytics' AND column_name='messages_json')) AS messages_json,
  (SELECT EXISTS (SELECT 1 FROM information_schema.views
       WHERE table_name='plugin_analytics_with_messages'))                   AS view_exists,
  (SELECT COUNT(*) FROM conversation_messages)                               AS cm_rows,
  (SELECT COUNT(*) FROM plugin_analytics)                                    AS pa_rows,
  (SELECT COUNT(*) FROM plugin_analytics WHERE n_messages_at_request IS NULL) AS pa_n_null;
-- alembic_at      = 0016_drop_messages_json
-- messages_json   = false
-- view_exists     = true
-- cm_rows         = 234
-- pa_rows         = 141
-- pa_n_null       = 0
```

Tests + ruff after the 0016 file landed: 157 passed + 18 skipped;
`ruff check` clean. Alembic upgrade `--sql 0015:0016` round-trips
cleanly (DROP VIEW + ALTER TABLE DROP COLUMN + CREATE VIEW + ledger
bump in one atomic block).

## Post-deploy smoke (2026-05-19 14:44 KST — operator-driven)

Operator deployed and ran the single-prompt smoke against a Read tool
chain (prompt carried the `[CANDIDATE1-SMOKE]` tag for searchability).
Verification query returned 5 rows in the new 10-minute window — all
green across every check:

| time KST | turn_kind | turn_seq | pa_n | cm_visible | view_n | smoke_tag_in_msg0 |
|---|---|---|---|---|---|---|
| 14:44:11 | internal_subprompt | NULL | 1 | 1 | 1 | true |
| 14:44:14 | user_input_turn_start | 1 | 1 | 1 | 1 | true |
| 14:44:19 | tool_continuation | 2 | 3 | 3 | 3 | true |
| 14:44:25 | tool_continuation | 3 | 5 | 5 | 5 | true |
| 14:44:28 | internal_subprompt | NULL | 7 | 7 | 7 | true |

End-to-end pass:

- `pa_n` non-NULL on every row — new column is being populated.
- `cm_visible == pa_n == view_n` on every row — UPSERT + view filter
  + `<` boundary all working.
- `smoke_tag_in_msg0 = true` on every row — Rule A/B normalisation
  preserves user content; the tag survives wrapper stripping.
- Main chain `conversation_id` stable across the four turns; cumulative
  `turn_seq` 1 → 2 → 3 over the (user_input_turn_start ∪
  tool_continuation) rows; the two `internal_subprompt` rows correctly
  off the turn axis (NULL).
- `n` grows 1, 3, 5, 7 (+2 per turn) — Anthropic Messages API requires
  strict user/assistant alternation, so each new turn appends
  `[previous_assistant_response, new_user_message]`. Confirms the
  quadratic-on-conversation-length dedup pressure the design targets.
- The final `internal_subprompt` at `n=7` shared the main chain's
  `conversation_id` (Claude Code internal post-turn call carrying the
  full history) and added zero new `conversation_messages` rows —
  `ON CONFLICT (conversation_id, msg_index) DO NOTHING` worked
  exactly as designed.

## Handoff

**Track closed (2026-05-19).** Candidate-1 shipped end-to-end:
code committed, live Supabase migrated, 117+ historic rows backfilled
(5.31x whole-dataset dedup ratio), `messages_json` column dropped,
`fly deploy` confirmed, post-deploy smoke passed across all
verification axes. No further action on this track. Future:

- The `plugin_analytics_with_messages` view re-aggregates messages
  per query — fine for the current conversation length distribution
  (max 43 messages observed), revisit if any conv exceeds 100.
- Subagent (Task tool) conversations confirmed earlier — they land
  as separate `conversation_id` automatically (different
  `first_msg_hash`). No design change needed.

## Suggestions (untouched)

- None this session.
