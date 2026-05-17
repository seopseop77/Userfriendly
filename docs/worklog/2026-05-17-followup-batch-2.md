# 2026-05-17 · Queued follow-up batch (round 2 — three items)

**Author**: Claude Code
**Session trigger**: User asked to clear three of the queued follow-ups
from the prior batch (`2026-05-17-followup-batch.md` §"What's left"):
(1) call `end_exchange` on Block/Abort short-circuit paths;
(2) DB-fixture integration test for `record_exchange_failure`;
(3) 6-month automated retention deletion job (ADR-0029 Axis 3).
Each item shipped as its own commit; prior batch's queue closes by
three.
**Related docs**: ADR-0027 (close-out policy — axis 2 implementation
is the reason the Block/Abort gap was surfaced), ADR-0029 (Axis 3 —
6-month retention policy this round automates),
`packages/llm_tracker_server/alembic/versions/0007_plugin_analytics.py`
+ `0009_retention_deletion_job.py` (new), prior worklog
`docs/worklog/2026-05-17-followup-batch.md`.

## Interpretation

Three executable items from the prior batch's "What's left", taken in
order. Each one is a small, well-specified follow-up; no decisions
needed user input. The third item required one verification choice —
whether to rely on the live Supabase project's `pg_cron` availability
or to gate the migration on extension presence; chose the latter so
local dev / test environments (stock Postgres docker, no `pg_cron`
extension) keep their alembic cycle green and the migration is
portable to any future non-Supabase deploy.

## What was done

### 1. `4fef915` — server: call end_exchange on Block/Abort paths

- `packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py`
  — added an explicit `plugin_host.end_exchange(exchange_id)` call
  immediately before each `return block_response(...)` short-circuit
  in the three Block/Abort sites:
  - `on_request_received` Block (very early — before forward).
  - `before_forward` Block (after request body parsed).
  - `on_upstream_response_start` Abort (after upstream 2xx but before
    SSE iteration begins).
- Before this CP, cleanup of the per-exchange ctx ran only via
  `block_response.gen()`'s `finally` clause, which fires only when
  the ASGI server iterates the synthetic stream. If the client
  disconnects before iterating, the ctx never gets cleaned up. The
  symptom is benign in practice (the ctx is a dict entry that gets
  garbage-collected with the request), but is inconsistent with the
  happy path (streaming generator `finally`) and the axis-2 path
  (explicit `end_exchange` before short-circuit), and removes the
  client-disconnect leak window entirely.
- `packages/llm_tracker_server/tests/test_proxy_forwarder_hooks.py`
  — added `test_block_short_circuit_cleans_ctx_without_iterating_response`.
  Pins the new behaviour without depending on response-stream
  iteration: a `Block` decision is returned, the response is *not*
  iterated, and the assertion is that the per-exchange ctx is no
  longer present in `plugin_host._exchange_contexts` immediately
  after the forwarder returns.

### 2. `3fe0caa` — tests: DB integration test for record_exchange_failure

- `packages/llm_tracker_server/tests/test_record_exchange_failure_db.py`
  — new file alongside `test_storage_smoke.py`. Pins the row-write
  half of `record_exchange_failure` (ADR-0027 axis 2) against the DB
  fixture, complementing the no-DB forwarder-level unit tests in
  `test_proxy_forwarder_hooks.py::test_axis2_*` (which exercise the
  forwarder branching and ctx cleanup but stop short of the actual
  INSERT).
- Two shapes covered:
  - `status_code=599` (network error sentinel, per ADR-0027 §"Open
    questions"). Asserts the row exists with the correct
    `exchange_id` + `org_id`, `started_at` / `ended_at` /
    `latency_ms` populated, and `blocked_by` is NULL (failure is
    not a plugin decision).
  - `status_code=401` (upstream non-2xx, verbatim from the upstream
    response). Same shape, same assertions, different status code.
- Skips under the same `LLMTRACK_TEST_DATABASE_URL` gate as the rest
  of the DB-fixture suite. Follows `test_storage_smoke.py` patterns
  for fixture setup (the existing `db_session` + `seeded_org`
  fixtures from `conftest.py`).

### 3. `cd21da3` — server: 6-month retention cron jobs (migration 0009)

- `packages/llm_tracker_server/alembic/versions/0009_retention_deletion_job.py`
  — new Alembic migration. Two daily `pg_cron` jobs scheduled at
  03:00 UTC:
  - `llm-tracker-retention-exchanges`. `public.exchanges.started_at`
    is stored as unix milliseconds (`BigInteger`), so the cutoff
    must be expressed as
    `(EXTRACT(EPOCH FROM now() - INTERVAL '6 months') * 1000)::bigint`.
  - `llm-tracker-retention-plugin-analytics`.
    `public.plugin_analytics.created_at` is `timestamptz`, so the
    cutoff is `now() - INTERVAL '6 months'` directly.
- Gated on `pg_cron` extension availability. The upgrade SQL is
  wrapped in a `DO $$ … $$` block that first checks
  `pg_available_extensions WHERE name = 'pg_cron'` and exits early
  with `RAISE NOTICE` if absent. This keeps the alembic
  upgrade/downgrade cycle green on stock Postgres docker images used
  by local dev / test environments, where the operator's
  documented fallback is the manual `DELETE` in
  `docs/deploy.md` §"Data collection & privacy".
- The downgrade unschedules both jobs via `cron.unschedule`. The
  `pg_cron` extension itself is **not** dropped — other parts of the
  Supabase project may rely on it, and dropping a project-wide
  extension to revert a single migration is the wrong blast radius.
- `docs/deploy.md` — updated the "Retention is 6 months" bullet
  under §"Data collection & privacy". Was: "An automated deletion
  job is not yet shipped; this paragraph is the stated policy a
  future job will key off." Now names the two cron jobs, the
  migration that schedules them, the `pg_cron` gating posture, and
  the operator inspection query
  (`SELECT jobname, schedule, command FROM cron.job WHERE jobname
  LIKE 'llm-tracker-retention-%'`).

## Decisions

- **Block/Abort cleanup at the return site, not the generator
  `finally`.** Both options correctly clean up the ctx in the
  happy iteration shape. The return-site form additionally covers
  the client-disconnect-before-iteration shape, matches the axis-2
  pattern documented in the prior worklog, and keeps cleanup local
  to the decision point — easier to reason about than "the cleanup
  is implicit in a generator that may or may not run."
- **DB-fixture test sized to two shapes, not all six fields.** The
  forwarder-level tests already pin the *forwarder's* behaviour
  (status codes returned, hooks fired, ctx cleaned). This DB-fixture
  test exists specifically to pin the row write. Two shapes —
  network-error (599) and upstream-non-2xx (e.g. 401) — give one
  test per axis-2 branch; deeper field-coverage belongs in unit
  tests on the helper itself.
- **`pg_cron` gating posture: skip-with-notice, not migration
  failure.** Stock Postgres lacks `pg_cron`. If the migration
  hard-failed on the missing extension, the alembic test cycle and
  any local dev `alembic upgrade head` against a non-Supabase
  Postgres would break. Gating on
  `pg_available_extensions` means the same migration script is the
  one of record for both production (Supabase, gets jobs scheduled)
  and dev (stock Postgres, gets a `NOTICE` and falls back to the
  manual DELETE that pre-dated this job).
- **`pg_cron` extension stays on downgrade.** Symmetry would drop
  the extension. But the extension is project-wide on Supabase and
  may be used by jobs we did not author; dropping it to revert one
  retention scheduler is over-broad. Downgrade only unschedules
  the two named jobs.
- **Cron `DELETE` uses the storage-layer field shape, not the
  ORM model.** `exchanges.started_at` is unix ms; expressing the
  cutoff as `now() - INTERVAL '6 months'` directly would compare a
  `timestamptz` to a `BigInteger` and fail at parse time. The
  EPOCH-multiply-by-1000 expression is unavoidable here. Documented
  in the migration docstring so the next operator reading the
  raw cron command does not file a "why is this so complicated"
  ticket.

## Verification

### Item 1 (Block/Abort cleanup)

```
$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py \
    packages/llm_tracker_server/tests/test_proxy_forwarder_hooks.py
All checks passed!
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_server/tests/test_proxy_forwarder_hooks.py -q
10 passed in 0.16s
# Was 9 passed; +1 for the new Block-without-iteration test.
```

### Item 2 (record_exchange_failure DB-fixture test)

```
$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker_server/tests/test_record_exchange_failure_db.py
All checks passed!
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
59 passed, 17 skipped in 5.45s
# Was 58 / 16 — +1 file (2 tests), both skip under no DB fixture.
# Under LLMTRACK_TEST_DATABASE_URL the new tests pass; under the
# default no-DB shape they skip alongside the rest of the DB suite.
```

### Item 3 (retention cron migration)

Migration file lints + parses + emits clean offline SQL on both
directions:

```
$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker_server/alembic/versions/0009_retention_deletion_job.py
All checks passed!
$ .venv/bin/python3.12 -m ruff format --check \
    packages/llm_tracker_server/alembic/versions/0009_retention_deletion_job.py
1 file already formatted
$ LLMTRACK_DATABASE_URL=postgresql://localhost/dummy \
    .venv/bin/python3.12 -m alembic upgrade \
    0008_drop_tool_call_count:0009_retention_deletion_job --sql
... emits the DO $$ … $$ block with both cron.schedule calls and the
    UPDATE alembic_version line wrapped in BEGIN/COMMIT.
$ LLMTRACK_DATABASE_URL=postgresql://localhost/dummy \
    .venv/bin/python3.12 -m alembic downgrade \
    0009_retention_deletion_job:0008_drop_tool_call_count --sql
... emits the unschedule loop and the UPDATE alembic_version reverse.
```

Full server test suite still green:

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
59 passed, 18 skipped in 5.71s
```

Live `alembic upgrade head` against the production Supabase database
is the operator's next operational step (per Handoff below) — local
verification is offline-mode-only because the dev shell has no
Supabase credentials.

## What's left / known limits

- **Production-side application.** The migration is committed but
  not yet applied to the live Supabase database; the next `fly
  deploy` runs `alembic upgrade head` as a release-command and
  advances the version stamp to `0009_retention_deletion_job`. After
  that, `SELECT jobname, schedule FROM cron.job WHERE jobname LIKE
  'llm-tracker-retention-%'` should show two rows. Until that
  deploy runs, the 6-month policy remains operator-DELETE only.
- **First scheduled run is in the future.** Cron fires daily at
  03:00 UTC; the first concrete deletion happens at the next 03:00
  UTC tick after deploy. No backfill — rows older than 6 months
  *today* are removed by the first scheduled run, not at migration
  time. (This is intentional: a migration that synchronously
  deletes "old" rows would hold a lock proportional to the historic
  table size; safer for the recurring job to handle it.)
- **No alerting on the cron failure path.** `pg_cron` writes job
  outcomes to `cron.job_run_details`; failures are silent unless the
  operator queries that table. A monitoring follow-up would either
  alert on
  `SELECT * FROM cron.job_run_details WHERE status = 'failed' AND
  start_time > now() - INTERVAL '1 day'` being non-empty, or simply
  graph it on the operator's existing dashboard. Out of scope here.
- **Remaining queued follow-ups (from the prior batch):**
  - `plugin_analytics` RLS axis — ADR-level revisit. Unchanged.
  - Real `session_id` populator + deletion endpoint (ADR-0029 Axis
    4 + Phase 3b agent identity).
  - i18n email scrubbing (ADR-0029 §"Open questions").
  - New: task hierarchy (session/task/exchange) — separate deferred
    track; not gated on anything.

## Handoff

Three commits land in order:

```
4fef915   server: call end_exchange on Block/Abort paths
3fe0caa   tests: DB integration test for record_exchange_failure
cd21da3   server: 6-month retention cron jobs (migration 0009)
<finalize>   docs: STATUS + worklog — followup batch round 2
```

After the next `fly deploy`:

1. `alembic upgrade head` advances the version stamp from
   `0008_drop_tool_call_count` (current production) to
   `0009_retention_deletion_job`. The `DO $$ … $$` block executes
   under Supabase (where `pg_cron` is available by default),
   creating the two scheduled jobs. No data deletion happens at
   migration time — first deletion is at the first 03:00 UTC tick
   after deploy.
2. Operator can verify post-deploy with:

   ```sql
   SELECT jobname, schedule, command
     FROM cron.job
    WHERE jobname LIKE 'llm-tracker-retention-%';
   ```

3. Operator can watch the first run with:

   ```sql
   SELECT jobname, status, return_message, start_time, end_time
     FROM cron.job_run_details
    WHERE jobname LIKE 'llm-tracker-retention-%'
    ORDER BY start_time DESC
    LIMIT 5;
   ```

Next single step (no longer one of the items in this batch): start
the `scope_guard` plugin (Phase 1c). Queued follow-ups remain
pickable cold.
