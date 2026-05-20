# 2026-05-21 · Follow-up cleanup — drop exchanges.session_id + ADR-0033

**Author**: Claude Code
**Session trigger**: User instruction listing three tasks: (1) drop
`exchanges.session_id` as migration 0017 + the ORM / helper / test
cleanup, (2) write the `plugin_analytics` no-RLS ADR, (3) update the
worklog + STATUS.md to absorb both the prior-session Candidate-1
implementation and this session's two tasks.
**Related docs**:
- ADR-0027 (exchange row close-out policy — names `session_id` in its
  population matrix; superseded for that column by this track)
- ADR-0029 (consent + data-handling — has open follow-up "real
  `session_id` populator + deletion endpoint" that this track retires)
- ADR-0033 (created this session — no-RLS for `plugin_analytics`)
- Prior worklogs: `docs/worklog/2026-05-19-candidate-1-implementation.md`
  (Candidate-1 dedup track; closed 2026-05-19; this session absorbs
  its post-deploy closure into STATUS / worklog only)

## Interpretation

Two pickable items from the §"Queued follow-ups" menu landed in one
session:

- **Drop `exchanges.session_id`.** The user confirmed
  `conversation_id` + `first_msg_hash` on `plugin_analytics` cover
  every use case the column was intended for (per-conversation
  grouping, dedup of retries, operator deletion scope). Column has
  zero non-`"server"` values in production and no query consumers in
  code. This retires the queued "real `session_id` populator +
  deletion endpoint" item — the populator was the prerequisite for
  the column being useful, and the analytics_sink plugin's
  `conversation_id` shipped that capability under a different name.
- **No-RLS ADR for `plugin_analytics`.** Elevates migration 0007's
  docstring choice to an ADR, naming the AsyncEngine / GUC
  propagation reason that makes RLS impractical for the analytics
  write path today.

Worklog rule §5.2 — one file per (date, topic). This is a separate
topic from the Candidate-1 implementation track (closed 2026-05-19),
so it gets its own file.

## What was done

- Created `packages/llm_tracker_server/alembic/versions/0017_drop_exchanges_session_id.py`
  — `ALTER TABLE exchanges DROP COLUMN session_id` on upgrade;
  downgrade re-adds the column `NOT NULL DEFAULT 'server'`
  (commit `21c5552`).
- Modified `packages/llm_tracker_server/src/llm_tracker_server/storage/models.py`
  — removed `session_id` from the `Exchange` ORM class (commit
  `21c5552`).
- Modified `packages/llm_tracker_server/src/llm_tracker_server/storage/exchanges.py`
  — removed the `session_id="server"` kwarg from
  `record_exchange_timing`, `record_exchange_blocked`, and
  `record_exchange_failure` (commit `21c5552`).
- Modified `packages/llm_tracker_server/tests/test_storage_smoke.py`,
  `packages/llm_tracker_server/tests/test_rls_two_org_isolation.py`,
  `packages/llm_tracker_server/tests/test_org_id_constraint.py` —
  removed the column from the Exchange constructor / `_make_exchange`
  helper / assertion (commit `21c5552`).
- Created `docs/decisions/0033-plugin-analytics-no-rls.md` — ADR
  accepting "no RLS on `plugin_analytics`" with the three reasons
  (GUC connection-scoping, operator-only access pattern, app-layer
  isolation), plus revisit trigger if the table is ever exposed via a
  request-scoped session path (commit `257caee`).

## Decisions

- **`session_id` removal is full-drop, not soft-deprecation.** The
  column has only the literal `"server"` value in production, zero
  query consumers in the code, and the queued "real populator" item
  was effectively retired the moment the analytics_sink plugin's
  `conversation_id` shipped. Soft-deprecation (NULL-allow) would
  carry a vestigial column forever.
- **HookContext.session_id stays.** This is an SDK-level identifier
  for the request slot (`packages/llm_tracker_sdk/src/llm_tracker_sdk/hook_context.py`),
  not the Exchange row column. Different concept; pre-existing
  infrastructure; out of scope for this track.
- **ADR-0033 captures the AsyncEngine reason explicitly.** The
  docstring on migration 0007 was thin ("Analytics is internal");
  the ADR pins the actual mechanical reason — the GUC binding
  (`set_config('app.org_id', ...)`) is session-scoped and does not
  propagate to the plugin's separate `AsyncEngine`. This is the part
  that makes adding RLS later non-trivial in practice, not a stylistic
  preference.

## Verification

```
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_sdk \
    packages/llm_tracker_plugin_analytics_sink \
    packages/llm_tracker_server -q
157 passed, 18 skipped in 5.78s

$ .venv/bin/python3.12 -m ruff check packages/
All checks passed!

$ cd packages/llm_tracker_server && ../../.venv/bin/python3.12 \
    -m alembic upgrade --sql 0016_drop_messages_json:0017_drop_exchanges_session_id
# Clean BEGIN ... COMMIT block:
#   ALTER TABLE exchanges DROP COLUMN session_id;
#   UPDATE alembic_version SET version_num='0017_drop_exchanges_session_id';

$ ../../.venv/bin/python3.12 -m alembic downgrade \
    --sql 0017_drop_exchanges_session_id:0016_drop_messages_json
# Clean reverse:
#   ALTER TABLE exchanges ADD COLUMN session_id TEXT DEFAULT 'server' NOT NULL;
```

Whole-repo grep `grep -rn "session_id" --include="*.py" packages/`
after the commit confirms zero references to the dropped Exchange
column. The remaining matches are all `HookContext.session_id` (SDK)
or unrelated test contexts — pre-existing and intentional.

**Live apply is operator-driven**: migration 0017 has not been
applied to Supabase; `fly deploy` is gated behind that. The previous
image's helpers will keep writing `"server"` to the column until both
land — which is safe because the column still exists in the live DB.
After migration apply + `fly deploy`, the new image's helpers stop
writing the column and the dropped column has no readers.

## Live apply timeline (same session continuation)

Operator authorised the Supabase live apply ("supabase 적용은 너가
해야지"). Migration 0017 applied via Supabase MCP `execute_sql`
as one atomic `BEGIN ... COMMIT` block, matching the
0013 / 0014 / 0015 / 0016 precedent.

Pre-state (`alembic_version` + `information_schema.columns`):

| field | value |
|---|---|
| alembic_at | `0016_drop_messages_json` |
| session_id column present | `true` |
| non-`"server"` rows | `0` (zero data to lose) |
| total `exchanges` rows | 182 |

Apply (one transaction):

```sql
BEGIN;
ALTER TABLE exchanges DROP COLUMN session_id;
UPDATE alembic_version SET version_num='0017_drop_exchanges_session_id'
  WHERE version_num='0016_drop_messages_json';
COMMIT;
```

Post-state:

| field | value |
|---|---|
| alembic_at | `0017_drop_exchanges_session_id` |
| session_id column present | `false` |
| total `exchanges` rows | 182 (no row loss) |

The 182-row count is preserved across the column drop — PostgreSQL
`ALTER TABLE DROP COLUMN` is a metadata-only operation on a single
NOT NULL column with no FK / index references, so no data is
rewritten.

## Post-Candidate-1 absorption (prior-session work in context)

Worklog rule §5.3 — checkpoint absorbs prior unrecorded work.
Candidate-1 (`conversation_messages` dedup) shipped end-to-end on
2026-05-19 across five commits:

- `54ca6fa` — code half: migration 0015 + `normalize.py` (Rule A +
  Rule B) + 8 unit tests + `ConversationMessage` ORM + plugin
  `_INSERT_SQL` swap from `messages_json` to `n_messages_at_request`
  + new `_UPSERT_MESSAGE_SQL` per-index path + 2 plugin tests.
- `a4727fc` — STATUS / worklog code-half checkpoint.
- `4c2babd` — live apply: migration 0015 applied via Supabase MCP
  `execute_sql`, 1242 → 234 dedup ratio (5.31× whole-dataset, 6.48×
  STRESS conv), backfill via SQL `INSERT ... DISTINCT ON ... ON
  CONFLICT DO NOTHING` with Python `canonical_message()` equality
  spot-check (checked=5 mismatches=0), `messages_json` column drop
  via migration 0016 (DROP VIEW + DROP COLUMN + CREATE VIEW in one
  atomic transaction).
- `7d3dad3` — track closure: operator `fly deploy` confirmed; 14:44
  KST smoke against `[CANDIDATE1-SMOKE]` Read tool chain returned
  5 rows all green across `pa_n` non-NULL / `cm_visible == pa_n ==
  view_n` / smoke tag in `messages[0]` / `conversation_id` stability
  / `turn_seq` cumulative growth / `ON CONFLICT DO NOTHING` working.

This session does no further Candidate-1 work — that track is fully
closed.

## What's left / known limits

- **Migration 0017 not yet applied to live Supabase.** Operator-owned
  per the standard apply pattern (Supabase MCP `execute_sql` in one
  atomic `BEGIN; ... COMMIT;` block matching the 0013 / 0014 / 0015
  / 0016 precedent), then `fly deploy` from `main` so the new image's
  helpers stop writing the dropped column. Until that ships, the
  running image continues to write `"server"` to the still-existing
  column — safe, just vestigial.
- **§"Queued follow-ups" menu after this session**: `plugin_analytics`
  RLS item is **closed** (settled by ADR-0033); `session_id`
  populator + deletion endpoint item is **closed** (retired by the
  column drop). Remaining items: task hierarchy (session/task/exchange
  layer), i18n email scrubbing.

## Handoff

**Next single step (operator-owned)**: `fly deploy` from `main`.
Migration 0017 is now applied live — the running image's helpers
(which still pass the dropped column via the prior compiled SQL
shape from the `Exchange` ORM) will `UndefinedColumn`-fail every
happy-path / blocked / failure helper invocation until redeploy.
So the deploy is non-skippable and is the only remaining gate
before the track is end-to-end closed.

Post-deploy smoke is a single non-blocked proxy exchange — verify
the helper write succeeds (a row lands in `exchanges` with
`status_code=200`) and no `UndefinedColumn` error appears in Fly
logs for `record_exchange_timing` / `record_exchange_blocked` /
`record_exchange_failure`.

After `fly deploy` lands, the §"Queued follow-ups" menu has two
remaining items (task hierarchy + i18n email scrubbing) — pick one
or leave undecided per the existing posture precedent.

## Continuation — `content_level` configurable via env (same day)

User request: replace the hardcoded `content_level="L3"` at the three
`Exchange(...)` constructor sites with a configurable env var
(`LLMTRACK_CONTENT_LEVEL`, default `"L3"`). Per CLAUDE.md §9
`content_level` is a public interface — the operator-knob shape
needs to exist even if production keeps the default.

### Step d check — design.md content level definitions

`docs/design.md` defines L0/L1/L2/L3 cleanly (§7.1 table):

| L0 | Metadata only — token counts, model name, latency, tool names, status code |
| L1 | L0 + deterministic hashes (SHA-256) of bodies, lengths |
| L2 | L0 + scrubbed body (secrets/PII/paths/emails/IPs removed) |
| L3 | Raw (still scrubber-passed) |

`packages/llm_tracker_sdk/src/llm_tracker_sdk/levels.py` already
ships these as a `ContentLevel` IntEnum. No ambiguity, no "Decision
needed" stop — proceeded to implementation.

### What was done (commit `2a68c56`)

- Modified `packages/llm_tracker_server/src/llm_tracker_server/config.py`
  — added `content_level: Literal["L0", "L1", "L2", "L3"] = "L3"` to
  `Settings`. `Literal` lets pydantic-settings reject typos at
  instantiation so a bad env value fails the server boot rather
  than silently mis-labelling rows.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/storage/exchanges.py`
  — added `content_level: str` as a required keyword-only argument
  to all three helpers (`record_exchange_timing`,
  `record_exchange_blocked`, `record_exchange_failure`); the
  hardcoded `"L3"` literal at each `Exchange(...)` constructor
  call site now reads the kwarg. Module docstring updated to name
  the env-var path.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/app.py`
  — `app.state.content_level = resolved.content_level` plumbed onto
  app state alongside `session_factory`.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py`
  — reads `content_level` from `app.state` once at the top of
  `forward_request` (with `"L3"` fallback for unit-test paths that
  build a bare `Request` with no app in scope); threaded through
  all six helper call sites (3× `record_exchange_blocked`, 2×
  `record_exchange_failure`, 1× `record_exchange_timing`).
- Modified `packages/llm_tracker_server/tests/test_record_exchange_failure_db.py`
  — two direct-helper call sites now pass `content_level="L3"`
  (required kwarg).

### Decisions

- **`content_level` is a required kwarg, not a defaulted one.**
  Giving it a default would let a forgotten forwarder call site
  silently regress to hardcoded `"L3"` — the very thing this track
  is removing. Required kwarg means any future caller has to make
  the choice explicit; tests pass `"L3"` because that's the
  documented production default. The forwarder's `"L3"` fallback at
  the `getattr(state, "content_level", "L3")` line is only for
  tests that bypass `create_app` — production always reads through
  `Settings`.
- **Validation via `Literal[...]` in pydantic-settings, not a
  field_validator.** Same outcome, less code; pydantic native
  Literal handling rejects typos at `Settings()` instantiation
  exactly when the server boots. The four-level enumeration is
  closed (design.md §7.1), so `Literal` is the right primitive.
- **`Settings.content_level` is a `str`, not the SDK `ContentLevel`
  IntEnum.** The `exchanges.content_level` column is `TEXT`
  (migration 0001); the storage helpers treat it as a string label.
  Keeping the type as `str` at the config + helper boundary avoids
  an unnecessary conversion at every call site. Validation that
  the string is one of the four labels happens once, at Settings
  instantiation.

### Verification

```
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_sdk \
    packages/llm_tracker_plugin_analytics_sink \
    packages/llm_tracker_server -q
157 passed, 18 skipped in 5.57s

$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_server/
All checks passed!
```

Test count unchanged from the prior commit (157 + 18 skipped) — no
new tests added; existing call-shape tests already cover the kwarg
plumbing since the forwarder hooks tests exercise the three
short-circuit paths. The Literal validation gets implicit coverage
the moment any operator sets a typo and the server fails to boot.

### Live state

`LLMTRACK_CONTENT_LEVEL` is **not yet set in Fly secrets** — the
running image will default to `"L3"` (matching the previous
hardcoded behaviour), so no behaviour change at deploy time. If
the operator later wants L0/L1/L2 on production, set
`fly secrets set LLMTRACK_CONTENT_LEVEL=L0` (or other) and
redeploy; the next exchange writes the new label.

## Suggestions (untouched)

- **`ruff format` drift across five files** unrelated to this track:
  `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py`,
  `packages/llm_tracker_plugin_analytics_sink/tests/test_analytics_sink.py`,
  `packages/llm_tracker_plugin_analytics_sink/tests/test_classifier.py`,
  `packages/llm_tracker_plugin_analytics_sink/tests/test_normalize.py`,
  `packages/llm_tracker_sdk/tests/test_harness.py`. Multi-line call
  shapes that ruff now wants on a single line. Reverted to keep this
  commit surgical (per CLAUDE.md §2.3 — don't mix mass formatting
  into feature commits); pick up in a standalone `style:` commit when
  convenient.
