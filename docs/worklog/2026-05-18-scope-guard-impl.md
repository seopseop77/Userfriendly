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
| **CP1** | Migration `0010_scope_guard_tables` + STATUS.md docker image bump | **done** (commits `2511c3a` + `b6cdf5f`) |
| **CP2** | `packages/llm_tracker_plugin_scope_guard/` skeleton + manifest + workspace registration | **done** (commit `2fe84e6` + this docs finalize) |
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

### CP2 — scope_guard package skeleton + manifest (done; commit `2fe84e6` + this docs finalize)

- Created `packages/llm_tracker_plugin_scope_guard/pyproject.toml`
  (commit `2fe84e6`):
  - Hatchling build target, entry point `scope_guard` →
    `llm_tracker_plugin_scope_guard.plugin:ScopeGuard`.
  - Deps: `llm-tracker-sdk` (workspace), `sqlalchemy[asyncio]`,
    `asyncpg`, `pgvector>=0.2`, `python-ulid`, `structlog`. Matches
    the `analytics_sink` reference for the SQLAlchemy / asyncpg /
    ulid / structlog set; `pgvector` is new for the
    `vector(1536)` column adapter.
- Created
  `packages/llm_tracker_plugin_scope_guard/src/llm_tracker_plugin_scope_guard/plugin.toml`
  per ADR-0030 §D9 verbatim: `hooks = ["on_persisted"]`,
  `capabilities = ["egress_http"]`, `egress_destinations` for both
  OpenAI endpoints, `allowed_modes = ["R"]`,
  `min_content_level = "L3"`, `db_namespace = "scope_guard"`.
- Created `__init__.py` exporting `ScopeGuard`; `plugin.py` with
  the `ScopeGuard(BasePlugin)` skeleton (`on_persisted` no-op so
  the host's load + audit path can be exercised before the
  pipeline lands).
- Created five module stubs (`chunker.py`, `embeddings.py`,
  `judge.py`, `pipeline.py`, `storage.py`), each with a docstring
  pointing to the CP that fills it in (CP3..CP6).
- Modified `uv.lock` — `pgvector==0.4.2` + transitive `numpy==2.4.5`
  installed alongside the new workspace package.

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
- **CP2 deps: `pgvector>=0.2` added; `numpy` arrives transitively.**
  `pgvector` is the SQLAlchemy / asyncpg adapter for the
  `vector(1536)` column — required for CP5's `scope_chunks` write
  + max-cosine query path. `numpy` is a pgvector transitive that
  CP3's chunker can reuse for adjacent-sentence cosine
  similarity (avoids re-implementing the math in pure Python).
  `httpx` is intentionally **not** a direct dep — CP4 reaches
  OpenAI via `HostEgressClient`, which the host injects on
  `self.egress`. ADR-0030 §D3/§D4 are silent on Python packages;
  these are implementation-tier choices.

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

CP2 verified after the package skeleton landed:

```
$ .venv/bin/python -m ruff format packages/llm_tracker_plugin_scope_guard/
7 files left unchanged
$ .venv/bin/python -m ruff check packages/llm_tracker_plugin_scope_guard/
All checks passed!

$ uv sync
Resolved 63 packages in 307ms
   Building llm-tracker-plugin-scope-guard @ file:///...
Downloaded numpy
      Built llm-tracker-plugin-scope-guard @ file:///...
Installed 3 packages
 + llm-tracker-plugin-scope-guard==0.1.0
 + numpy==2.4.5
 + pgvector==0.4.2

$ .venv/bin/python -c "..."
manifest OK: scope_guard 0.1.0 hooks=['on_persisted']
  caps=['egress_http'] level=L3
egress: ['https://api.openai.com/v1/embeddings',
         'https://api.openai.com/v1/chat/completions']
db_namespace: scope_guard
entry points found: [EntryPoint(name='scope_guard',
   value='llm_tracker_plugin_scope_guard.plugin:ScopeGuard', ...)]
class loaded: ScopeGuard name attr = scope_guard
instance OK: scope_guard

$ .venv/bin/python -m pytest -q
164 passed in 25.03s
```

Four checks all green: ruff clean; `uv sync` installs the new
workspace package with `pgvector==0.4.2` (and transitive
`numpy==2.4.5`); `PluginManifest.from_path()` accepts the
ADR §D9 manifest verbatim; the `llm_tracker.plugins` entry point
group exposes `scope_guard` → `ScopeGuard`, which loads and
instantiates cleanly; full test suite stays at 164 (CP2 added zero
tests as designed — skeleton-only).

## What's left / known limits

- CP3–CP8 not started.
- ADR-0030's three remaining open questions (Q1 chunker algo,
  Q2 ANN index, Q4 judge prompt) get pinned at CP3, MVP-defer,
  CP4 respectively. Q3 was resolved at CP1 time (new 0011
  migration over amending 0009).
- Test baseline this session: **164 passed** with the DB fixture
  active against `pgvector/pgvector:pg15`. CP2 added zero new
  tests (skeleton only) and broke zero existing ones. CP3 will
  start adding unit tests; CP5 + CP6 add the larger DB-fixture
  integration tests.
- pgvector ANN index not present (ADR-0030 §Q2 defers it). When any
  org's `scope_chunks` count starts approaching ~10k, revisit and
  add an `HNSW` or `IVFFlat` index on `embedding`.
- `tests/` directory not yet created under
  `packages/llm_tracker_plugin_scope_guard/` and not yet
  registered in the root `pyproject.toml`'s `testpaths`. CP3 adds
  both atomically with the first chunker test.

## Handoff

CP1 + CP2 closed by commits `2511c3a` + `b6cdf5f` + `2fe84e6` +
this docs finalize. The active work board is the "Checkpoint
plan" table above: CP1 + CP2 done, CP3–CP8 pending.

**Next active step — CP3: `chunker.py` + unit tests.**
ADR-0030 §D5 spec:

1. Sentence-segment via MVP regex (ADR §D5 §1 pins the pattern:
   `[.?!。？！]` + whitespace + capital / line-break heuristic).
2. Embed each sentence with the OpenAI
   `text-embedding-3-small` client — for CP3 the chunker takes an
   injected `embed(text) -> list[float]` callable so the test
   can stub it without making real API calls (the real client
   lands in CP4).
3. Walk adjacent cosine similarities. Insert a chunk boundary
   where the similarity drops below a rolling-mean baseline
   (**Q1: pin the exact threshold + window size at this CP** —
   benchmark a small set of fixture documents against two or
   three candidate parameterisations and freeze one in the
   module).
4. Enforce min 50 / max 500 token bounds (below-min merges with
   next; above-max splits on longest gap).

Numpy is now installed transitively via pgvector — the chunker
can use `numpy.dot` / `numpy.linalg.norm` for the cosine math
without a new direct dependency.

Output type for CP3:
`list[ChunkRecord]` where
`ChunkRecord = (chunk_index, content, embedding)`. The
`tools/process_scope_document.py` CLI in CP6 calls this and
hands the result to `storage.insert_chunks(...)` once that
function lands in CP5.

If the user is picking this up cold: STATUS.md → this worklog
→ last 4 commits (`2511c3a` + `b6cdf5f` + `2fe84e6` + finalize).
The Decisions section above carries the four ADR open-question
commitments so CP3/CP4/CP8 don't re-derive them.

## Suggestions (untouched)

- `CLAUDE.md §1` still lists "Mode-aware" as a core principle even
  though ADR-0019 retired L/A/R modes; `min_content_level` is what
  ADR-0030 binds against. Flagged here so a future CLAUDE.md touch
  can drop it.
- `docs/design.md` still describes the local-sidecar architecture in
  places; ADR-0017 + ADR-0019 + ADR-0030 together are owed a v0.3
  pass once scope_guard ships.
