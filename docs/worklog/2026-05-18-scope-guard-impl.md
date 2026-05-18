# 2026-05-18 · scope_guard plugin implementation (ADR-0030)

**Author**: Claude Code
**Session trigger**: User accepted ADR-0030 (Proposed → Accepted) and
asked Claude Code to plan + execute the implementation. User picked
Option A (`pgvector/pgvector:pg15` for the local test DB so ADR-0030
§D8's `CREATE EXTENSION vector` runs unconditionally — same as
Supabase) over Option B (gate the migration on `pg_available_extensions`
and skip locally).
**Related docs**: ADR-0030 (now Accepted), ADR-0017 (server pivot),
ADR-0018 (RLS), ADR-0026 (HookContext response accessors), ADR-0029
(consent + accessor scrubber), ADR-0015 (EgressClient SDK). Prior
worklog: `docs/worklog/2026-05-18-adr-0030-scope-guard.md` (ADR drafting).

## Interpretation

User asked: "Accept할게. 그럼 scope_guard 구현에 대한 계획을 짜고
실행할 수 있는거야?" then approved an 8-checkpoint plan and chose
Option A for the pgvector axis.

The ADR has 9 user-axes + 4 Cowork-axes all locked, so this is a
straight implementation session — no architectural decisions to make
beyond the four open questions ADR-0030 explicitly delegated to the
implementing session:

- **Q1** — chunker semantic-boundary algorithm. Picked at CP3 via
  small benchmark; pin in `chunker.py` with a comment.
- **Q2** — pgvector ANN index. ADR defers until org chunk count
  exceeds ~10k. MVP keeps linear scan; this session does not add an
  index.
- **Q3** — retention job split. Default this session picked: new
  `0011_scope_alerts_retention` migration mirroring 0009's
  `pg_cron` guard pattern, rather than amending 0009. Reason: each
  retention concern owns its own reversible migration; 0009 already
  has two cron rows and adding a third with a different table /
  column / time-unit shape muddies the downgrade.
- **Q4** — Stage-2 prompt template. Pinned as a frozen module-top
  string in `judge.py` at CP4; future tweaks become diff-visible.

Pre-flight sanity check (before CP1) found everything else in the
ADR matches the current codebase:

- `ctx.org_id` exists at `llm_tracker_sdk/hook_context.py:71` and is
  populated by the forwarder's `begin_exchange` from
  `request.state.org_id` (ADR-0026).
- `analytics_sink` is a 1:1 reference for the plugin shape:
  `on_init` builds an `AsyncEngine`, `on_persisted` inserts one
  row, `_engine_owned` flag controls dispose on `on_shutdown`.
- `HostEgressClient.fetch(url, *, method, headers, body, timeout)`
  returns `EgressResponse(status_code, headers, body)`; one client
  is constructed per loaded plugin at host-load time, baking in the
  plugin name. `self.egress` on `BasePlugin` is the access point.
- Workspace registration is glob-based (`[tool.uv.workspace]
  members = ["packages/*"]`); only `testpaths` needs a one-line
  edit when adding a new plugin package.
- Migration 0005 RLS pattern: `ENABLE` + `FORCE` RLS, two
  PERMISSIVE policies (`_org_isolation` + `_admin_access`) with
  `NULLIF(current_setting(...), '')::uuid` to handle Postgres GUC
  '' quirk. The plugin's tables follow this exactly for
  `scope_documents` + `scope_chunks`; `scope_alerts` follows the
  RLS-off `plugin_analytics` shape from migration 0007.

Local test DB was previously `postgres:15`; the same commit that
ships migration 0010 bumps STATUS.md §"Local dev loop revival" to
`pgvector/pgvector:pg15`.

## Checkpoint plan

| CP | Scope | Status |
|---|---|---|
| **CP1** | Migration `0010_scope_guard_tables` + STATUS.md docker image bump | **done** (commits `2511c3a` server + docs finalize) |
| CP2 | `packages/llm_tracker_plugin_scope_guard/` skeleton + manifest + workspace registration | queued |
| CP3 | `chunker.py` + unit tests; resolve Q1 | queued |
| CP4 | `embeddings.py` + `judge.py` via `HostEgressClient`; pin Q4 prompt | queued |
| CP5 | `pipeline.py` + `storage.py` + `plugin.py`; DB-fixture integration test | queued |
| CP6 | `tools/process_scope_document.py` CLI (.txt + .md, idempotent) | queued |
| CP7 | `.env.example` + `docs/deploy.md` §"Data collection & privacy" + `docs/plugins.md` §11 | queued |
| CP8 | `0011_scope_alerts_retention` migration (Q3 default: new migration, not amend 0009) | queued |

Each CP = 1 commit + worklog "What was done" append + STATUS.md
refresh (CLAUDE.md §5.3).

## What was done

### CP1 — migration 0010 + STATUS.md docker image (done; commit `2511c3a` server + docs finalize)

- Created `packages/llm_tracker_server/alembic/versions/0010_scope_guard_tables.py` (commit `2511c3a`):
  - `CREATE EXTENSION IF NOT EXISTS vector`.
  - Three tables (`scope_documents`, `scope_chunks`,
    `scope_alerts`) with column shapes from ADR-0030 §D8 verbatim,
    btree indexes per §D8, no pgvector ANN index (Q2 deferred).
  - RLS on `scope_documents` + `scope_chunks` (migration 0005
    pattern: ENABLE + FORCE + `_org_isolation` +
    `_admin_access`); no RLS on `scope_alerts` (migration 0007
    `plugin_analytics` pattern).
  - GRANT SELECT/INSERT/UPDATE/DELETE on all three tables to
    `llm_tracker_app`.
  - Reversible downgrade in reverse order. `vector` extension is
    left in place (same blast-radius reasoning as 0009 keeps
    `pg_cron`).
- Modified `docs/STATUS.md` — "Local dev loop revival" §:
  `postgres:15` → `pgvector/pgvector:pg15`, with a comment
  explaining why (migration 0010 requires the extension; vanilla
  image fails `alembic upgrade head` in `conftest.py`).
- Modified `docs/decisions/0030-scope-guard-plugin.md`:
  Status `Proposed` → `Accepted` with the user's acceptance date
  + pgvector Option A pre-decision noted.

## Decisions

- **Q3 default — new `0011_scope_alerts_retention` migration,
  not amend 0009.** Reason: each retention concern owns its own
  reversible migration; mixing a third cron row with different
  table/column/unit shape into 0009 muddies the downgrade. Not
  high-stakes either way — easy to reverse.
- **pgvector — Option A (image bump) over Option B (extension
  guard).** Reason: ADR-0030 §D8 explicitly assumes the extension
  is present ("already present on Supabase"). The 0009 guard
  precedent applies to `pg_cron` (operational-only) but does not
  carry over to `vector` (plugin-core data type). Surfaced this as
  a user-facing decision; user picked Option A.
- **No ANN index in MVP (Q2).** ADR-0030 defers until any org's
  chunk count exceeds ~10k. btree indexes on `org_id` +
  `document_id` cover the basic paths; the cosine-distance
  `ORDER BY` does a linear scan within an org's chunks.

## Verification

CP1 verified end-to-end against the new pgvector image:

```
$ docker rm -f llm-tracker-pg && docker run -d --name llm-tracker-pg \
    -e POSTGRES_USER=cp2 -e POSTGRES_PASSWORD=cp2 \
    -e POSTGRES_DB=llm_tracker_test \
    -p 55432:5432 pgvector/pgvector:pg15
# (image pulled, container up)

$ export LLMTRACK_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test
$ cd packages/llm_tracker_server && .venv/bin/python -m alembic upgrade head
# 0001 → 0002 → ... → 0010_scope_guard_tables; version stamped 0010

$ psql -c "\dt" -c "SELECT extname FROM pg_extension WHERE extname='vector'"
# scope_documents, scope_chunks, scope_alerts present; vector extension installed

$ .venv/bin/python -m alembic downgrade -1
# scope_* tables dropped; alembic_version → 0009

$ .venv/bin/python -m alembic upgrade head
# scope_* tables recreated; alembic_version → 0010 (round-trip clean)

$ export LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test
$ cd /Users/minseop/Desktop/MyProjects/Userfriendly && .venv/bin/python -m pytest -q
164 passed in 25.14s
```

The `164 passed` baseline is lower than STATUS.md's pre-archive
"354 passed under DB fixture" because the 2026-05-17 archive
session removed the local `llm_tracker` sidecar (`8ef166d`) and
rescued only the SDK tests into `packages/llm_tracker_sdk/tests/`.
The current sum across the six testpath entries is 164 — CP1 added
zero new tests and broke zero existing ones (regression-free).

Found and fixed during verification:

- **Multi-statement asyncpg issue.** Initial draft sent the whole
  schema block as one `op.execute(big_string)`; asyncpg rejected it
  with `cannot insert multiple commands into a prepared statement`.
  Migration `0009_retention_deletion_job` sidesteps the same trap by
  wrapping its body in a single `DO $$ ... END$$;` block. For 0010
  the cleaner fix is per-statement dispatch — a `_UPGRADE_STATEMENTS`
  tuple iterated with one `op.execute` per item. Same transactional
  guarantees (alembic wraps `upgrade()` in one DDL transaction),
  driver-friendly.

- **Stale `.git/HEAD.lock`.** A 0-byte HEAD.lock from earlier in the
  day (Cursor gitWorker, likely crashed) blocked the first commit
  attempt. Confirmed stale (>2h old, no active git mutating
  processes), removed manually. Standard git recovery, not
  destructive.

## What's left / known limits

- CP2–CP8 not started.
- ADR-0030's four open questions (Q1, Q2, Q3, Q4) get pinned at
  their respective CPs as listed in the Decisions section above.
- Test baseline for this session: **164 passed** with the DB
  fixture active against `pgvector/pgvector:pg15`. CP1 added zero
  new tests and broke zero existing ones. The earlier
  "354 passed" line in STATUS.md history reflects the pre-archive
  state before commit `8ef166d` removed the local sidecar; the
  comparable post-archive figure is the 164 number captured here.
- pgvector ANN index not present (ADR-0030 §Q2 defers it). When any
  org's `scope_chunks` count starts approaching ~10k, revisit and
  add an `HNSW` or `IVFFlat` index on `embedding`.

## Handoff

CP1 closed by commits `2511c3a` (server migration) + the
docs-finalize commit that lands this worklog + ADR Accepted +
STATUS.md refresh. The active work board is the "Checkpoint plan"
table above: CP1 done, CP2–CP8 pending.

**Next active step — CP2: scope_guard package skeleton.**
Create `packages/llm_tracker_plugin_scope_guard/` with the
`pyproject.toml` + `plugin.toml` shape from ADR-0030 §D9 (six
modules as empty stubs; manifest declares `egress_http` capability
and the two OpenAI destinations). Register the package in the root
`pyproject.toml` `[tool.pytest.ini_options].testpaths` once a
`tests/` directory exists. Verify with `uv sync` + a host-load
smoke test confirming the plugin appears in the audit log on
startup.

If the user is picking this up cold: STATUS.md → this worklog →
last 2 commits (`2511c3a` + docs finalize). The Decisions section
above carries the four ADR open-question commitments so CP3/CP4/
CP8 don't re-derive them.

## Suggestions (untouched)

- `CLAUDE.md §1` still lists "Mode-aware" as a core principle even
  though ADR-0019 retired L/A/R modes; `min_content_level` is what
  ADR-0030 binds against. Flagged here so a future CLAUDE.md touch
  can drop it.
- `docs/design.md` still describes the local-sidecar architecture in
  places; ADR-0017 + ADR-0019 + ADR-0030 together are owed a v0.3
  pass once scope_guard ships.
