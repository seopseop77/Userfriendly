# 2026-05-18 · storage schema cleanup (migration 0013)

**Author**: Claude Code
**Session trigger**: review the prior Cowork session's direct file edits
(commit `efc7fb4`), verify tests + lint pass, then apply migration 0013 to
production via the Supabase MCP and bundle worklog + STATUS as one
checkpoint.
**Related docs**: `docs/design.md`, `docs/decisions/0018-tenancy-and-org-id.md`,
prior worklog `docs/worklog/2026-05-17-followup-batch.md` (migration 0008
which dropped `tool_call_count` from `exchanges`).

## Interpretation

The user described `efc7fb4` as a Cowork-driven cleanup pass over schema
that was ported from the SQLite-era local sidecar but never wired through
on the server. Two distinct removals collapsed into one migration:

1. **Two whole tables** (`events`, `tool_calls`) with ORM models, alembic
   table definitions, and a single index — but no `INSERT` call sites
   anywhere in `packages/llm_tracker_server/`. They were dead schema.
2. **Six columns** that the analytics workstream made redundant — four
   token-count columns on `exchanges` (the authoritative copy lives on
   `plugin_analytics` since migration 0007), plus two never-or-redundantly
   filled columns on `plugin_analytics` (`tool_call_count` was always 0;
   `system_prompt` duplicated content already in `messages_json`).

The code edits in `efc7fb4` are surgical — ORM model removal, removal of
token kwargs from `record_exchange_timing`, matching forwarder call-site
trim, and analytics_sink + its tests adjusted for the simplified
`plugin_analytics` shape. This session does not change the code; it
verifies and ships the production-side half (live migration + docs).

## What was done

- Reviewed commit `efc7fb4` (7 files, +196 / -223). Each acceptance
  criterion confirmed by reading the post-commit file:
  - `record_exchange_timing` (`packages/llm_tracker_server/src/llm_tracker_server/storage/exchanges.py:46`)
    has no token parameters.
  - The happy-path call site in `forwarder.py:437` passes no token
    arguments (only `model_served` + `stop_reason` from the SSE extractor).
  - `analytics_sink._INSERT_SQL` (`packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py:17`)
    contains no `system_prompt` or `tool_call_count`.
  - `storage/models.py` contains no `Event` or `ToolCall` class; the
    module docstring documents the 0013 cleanup.
- Ran the targeted test suites — green:
  `pytest packages/llm_tracker_server/tests/ packages/llm_tracker_plugin_analytics_sink/tests/ -q`
  → 64 passed, 18 skipped.
- Ran `ruff check .` — `All checks passed!`
- Ran `ruff format --check .` — one **unrelated** file flagged
  (`packages/llm_tracker_sdk/tests/test_harness.py`, last touched in
  commit `3d76d1f` housekeeping — predates this work). Per CLAUDE.md §2.3
  (surgical changes) the format drift in an unrelated file is noted in
  §Suggestions below, **not** mixed into this checkpoint.
- Applied migration `0013_schema_cleanup` to the live Supabase project
  `qdcixbwwlsnkekabavmj` via the Supabase MCP `execute_sql` tool, wrapped
  in a single `BEGIN; … COMMIT;` block so all six DDL statements + the
  `alembic_version` bump land atomically.
- Verified post-state on the live DB:
  - `alembic_version.version_num` = `'0013_schema_cleanup'` (was
    `'0012_scope_chunks_embed_dim_768'`).
  - `events` and `tool_calls` no longer appear in
    `information_schema.tables` (public schema).
  - `exchanges` columns no longer include `input_tokens`, `output_tokens`,
    `cache_read_tokens`, `cache_write_tokens`. The 17 remaining columns
    match `models.Exchange` exactly.
  - `plugin_analytics` columns no longer include `tool_call_count` or
    `system_prompt`. The 13 remaining columns match `analytics_sink`'s
    `_INSERT_SQL` placeholders exactly.
- This worklog created + STATUS.md updated; docs-only commit closes the
  three-unit checkpoint (CLAUDE.md §5.3). The code half rode in `efc7fb4`.
- **Follow-up 2026-05-19**: operator confirmed `fly deploy` from `main`
  complete (smoke verification at operator discretion — not separately
  reported to this Claude Code session). Running image now matches the
  live schema; the schema-cleanup track is fully closed across code +
  live DB + running image. This worklog + STATUS.md updated again to
  reflect the closed posture (docs-only commit).

## Decisions

- **Apply the migration via raw SQL (`execute_sql`) rather than
  `apply_migration`.** Reason: schema migrations in this repo are owned
  by alembic, not by Supabase's migrations table. The `apply_migration`
  tool would create a parallel record in `supabase_migrations.schema_migrations`
  that is meaningless to alembic and would cause confusion on the next
  `alembic upgrade head`. The `UPDATE alembic_version` statement in the
  SQL block is what keeps the alembic ledger truthful — Fly's
  release-command-run `alembic upgrade head` will now see HEAD already
  applied and no-op on the next deploy.
- **Single `BEGIN; … COMMIT;` block** rather than statement-by-statement
  execution. Reason: partial failure in the middle of the block would
  leave alembic_version out of sync with the actual schema. The atomic
  block keeps the two ledger axes (schema state, alembic state)
  consistent on rollback.
- **Did not fix the unrelated `test_harness.py` format drift in this
  commit.** Reason: CLAUDE.md §2.3 "don't mix mass formatting into
  feature commits." Logged under §Suggestions.

## Verification

```
$ git show efc7fb4 --stat
 .../llm_tracker_plugin_analytics_sink/plugin.py    |  77 ++++-----------
 .../tests/test_analytics_sink.py                   |  25 ++---
 .../alembic/versions/0013_schema_cleanup.py        | 104 +++++++++++++++++++++
 .../src/llm_tracker_server/proxy/forwarder.py      |  11 +--
 .../src/llm_tracker_server/storage/__init__.py     |  27 ++----
 .../src/llm_tracker_server/storage/exchanges.py    |  91 +++++++-----------
 .../src/llm_tracker_server/storage/models.py       |  84 ++++-------------
 7 files changed, 196 insertions(+), 223 deletions(-)

$ pytest packages/llm_tracker_server/tests/ \
        packages/llm_tracker_plugin_analytics_sink/tests/ -q
...
64 passed, 18 skipped in 5.50s

$ ruff check .
All checks passed!

$ ruff format --check .
Would reformat: packages/llm_tracker_sdk/tests/test_harness.py
1 file would be reformatted, 108 files already formatted
# Unrelated; logged under §Suggestions.
```

**Live DB post-state** (Supabase project `qdcixbwwlsnkekabavmj`,
queried via Supabase MCP `execute_sql`):

```sql
-- alembic ledger advanced atomically with the schema changes
SELECT version_num FROM alembic_version;
-- → 0013_schema_cleanup

-- both tables gone from public schema
SELECT table_name FROM information_schema.tables
 WHERE table_schema='public' AND table_name IN ('events','tool_calls');
-- → []

-- four token columns gone from exchanges (17 cols remain; match models.Exchange)
SELECT column_name FROM information_schema.columns
 WHERE table_schema='public' AND table_name='exchanges'
 ORDER BY ordinal_position;
-- → id, session_id, started_at, ended_at, provider, endpoint,
--    model_requested, model_served, status_code, latency_ms,
--    stop_reason, t_request_received_ms, t_upstream_first_byte_ms,
--    t_client_first_byte_ms, content_level, blocked_by, org_id

-- two columns gone from plugin_analytics (13 cols remain; match _INSERT_SQL)
SELECT column_name FROM information_schema.columns
 WHERE table_schema='public' AND table_name='plugin_analytics'
 ORDER BY ordinal_position;
-- → id, exchange_id, org_id, created_at, model_requested,
--    model_served, messages_json, response_json, input_tokens,
--    output_tokens, cache_read_tokens, cache_write_tokens, stop_reason
```

The atomic block executed cleanly with no rollback. Production traffic
between the migration apply and the next Fly deploy is safe: code at
`efc7fb4` is what the upcoming image will run, and the live schema now
matches that code's shape.

## What's left / known limits

- ~~**No Fly deploy yet.**~~ **Closed 2026-05-19** — operator confirmed
  `fly deploy` from `main` complete. Running image now matches the live
  schema; happy-path `record_exchange_timing` flushes no longer attempt
  the four dropped `exchanges` token columns. Smoke verification of a
  single non-blocked exchange (clean `exchanges` row + no
  `record_exchange_timing` error in Fly logs) is at operator discretion
  and was not separately reported to this Claude Code session.
- **Alembic downgrade path** in `0013_schema_cleanup.py` restores the
  exact pre-0013 shape (nullable token columns on `exchanges`; restored
  `tool_calls`/`events` tables sans data; `system_prompt` + `tool_call_count`
  on `plugin_analytics`). Tested via `--sql` dry-run earlier in the Cowork
  session; not exercised against live DB. No data to backfill on
  downgrade — the token columns were always populated by `analytics_sink`
  into `plugin_analytics`, and the two dropped tables were always empty.
- **Suggestions** below logs one out-of-scope ruff format issue.

## Handoff

**Track closed (2026-05-19).** Migration `0013_schema_cleanup` is now
aligned across all three axes: code (`efc7fb4`), live Supabase schema
(applied 2026-05-18), and running Fly image (`fly deploy` confirmed by
operator 2026-05-19). Smoke verification (single non-blocked exchange →
clean `exchanges` row with `status_code=200` and no
`record_exchange_timing` error in Fly logs) is at operator discretion
and not separately reported to this session.

**Next single step (undecided)**: per the user's direction this session,
the next active track is intentionally left unpicked. The §"Queued
follow-ups" list under STATUS.md §"Current phase" is the open menu —
`plugin_analytics` RLS ADR-level revisit is the most-shovel-ready, but
task hierarchy / `session_id` populator + deletion endpoint / i18n
email scrubbing all remain available. scope_guard remains paused at
`0c1ca9d` per its handoff worklog — this schema cleanup does not change
that posture.

## Suggestions (untouched)

- `packages/llm_tracker_sdk/tests/test_harness.py` has accumulated
  one ruff format drift since commit `3d76d1f` (the housekeeping commit
  that rescued the SDK test files out of the deleted local sidecar).
  Not touched in this commit per CLAUDE.md §2.3. Single-line fix on a
  future docs/test housekeeping pass: `ruff format
  packages/llm_tracker_sdk/tests/test_harness.py`.
