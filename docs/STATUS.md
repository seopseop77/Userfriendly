# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-11 (Claude Code; Phase 3c CP2 landed — storage layer on PostgreSQL, two PG smoke tests green)
**Updated by**: Claude Code (Phase 3c CP2 checkpoint, source commit b7eed52)

## Current phase

- **Phase**: **Phase 3c — CP1 + CP2 closed (2/14).** CP1 brought up
  the `llm_tracker_server` FastAPI skeleton + `/healthz`. CP2 has
  ported the storage layer to PostgreSQL: SQLAlchemy async engine
  + asyncpg driver, four user-data ORM models with `BigInteger`
  for epoch-ms / counter columns, the Alembic env moved into the
  server package, and two migrations — `0001_initial_schema`
  (consolidates the SQLite-era initial + timing-column migrations)
  and `0002_audit_log_triggers` (a PL/pgSQL function + two
  `BEFORE ... FOR EACH ROW` triggers replacing SQLite's
  `RAISE(ABORT)` per-table form). Settings gained
  `LLMTRACK_DATABASE_URL`. Source HEAD now at `b7eed52`.
- **Active task**: **CP3 — `orgs` + `api_tokens` schema (ADR-0018
  substrate)** is the queued next commit. **ADR-#2 consent
  decision** remains the most blocking remaining Phase-3a item
  before *any external testing*; operator-only smoke (CP14) is not
  blocked.

## Active worklog

`docs/worklog/2026-05-11-phase3c-plan.md` (active; plan-only).
The prior signing-removal worklog
`docs/worklog/2026-05-11-signing-removal.md` is closed.

## Recent commits

```
b7eed52   server: port storage layer to PostgreSQL (CP2)
3f59576   docs: STATUS + worklog for Phase 3c CP1 checkpoint
7d992ff   server: bootstrap llm_tracker_server skeleton (CP1)
f866cb8   docs: STATUS + worklog for Phase 3c plan checkpoint
ec51a40   docs: Phase 3c build plan (14 checkpoints)
```

## Where we paused

**Phase 3c CP2 — storage layer on PostgreSQL — closed.** The
server now has a working PG storage stack:

- New deps in `packages/llm_tracker_server/pyproject.toml` runtime
  group: `sqlalchemy>=2`, `asyncpg`, `alembic`. `uv sync` only
  added `asyncpg==0.31.0` — `sqlalchemy` + `alembic` were already
  in the workspace lockfile via `packages/llm_tracker`.
- `Settings` gained `database_url: str = ""`
  (`LLMTRACK_DATABASE_URL`). The empty default keeps `/healthz`
  booting without a DB; the storage entry points raise
  `ValueError` if asked for an engine without a URL.
- New `packages/llm_tracker_server/src/llm_tracker_server/storage/`
  package: `engine.py` (`make_engine`,
  `make_session_factory`), `models.py` (four ORM models ported
  one-to-one from `llm_tracker.storage.models` with
  `BigInteger` substituted for `Integer` on every epoch-ms /
  counter column), and a flat `__init__.py` re-export.
- New Alembic env at `packages/llm_tracker_server/alembic/`:
  `alembic.ini`, `env.py` (reads `LLMTRACK_DATABASE_URL`),
  `script.py.mako`, `versions/0001_initial_schema.py`
  (consolidates SQLite-era initial + timing migrations into one PG
  port), `versions/0002_audit_log_triggers.py` (PL/pgSQL function
  `audit_log_reject_modify()` + two `BEFORE ... FOR EACH ROW`
  triggers — UPDATE + DELETE — replacing SQLite's `RAISE(ABORT)`
  per-table form).
- `tests/test_storage_smoke.py` exercises `alembic upgrade head`
  + `Exchange` round-trip + audit_log trigger rejection of UPDATE
  / DELETE. Skipped unless `LLMTRACK_TEST_DATABASE_URL` is set so
  the wider suite stays green on machines without a local PG.

Verification: PostgreSQL 15.17 container on port 55432 was used
for live round-trip. `pytest packages/llm_tracker_server/tests/test_storage_smoke.py
-q` → 2 passed in 1.72 s. Full suite with the test URL set:
`pytest -q` → 251 passed, 4 warnings. Full suite *without* the
test URL: → 249 passed, 2 skipped, 4 warnings — the four warnings
are the pre-existing `fork()` warnings from `cli/manage.py`,
unchanged. Ruff: 0 errors; 12 files already formatted. See
`docs/worklog/2026-05-11-phase3c-plan.md §Verification §CP2` for
the captured outputs (offline-mode SQL gen + live container run
+ docker teardown).

Three CP2-specific deviations from the original plan, all flagged
in the worklog §Decisions §CP2:

1. **String/ULID primary keys preserved** on the four ported
   tables. The plan mentioned BIGINT identity / `gen_random_uuid()`
   defaults, but Phase 1/2 callers all produce ULID strings at the
   application layer — the identity/UUID guidance is taken as
   forward-pointing for the CP3 tenancy tables (`orgs.id UUID`),
   not retroactive rework. Flagged so a future reader doesn't try
   to "finish" the swap.
2. **CP2 consolidates two SQLite migrations into a single PG
   `0001_initial_schema`.** Greenfield server schema — replaying
   the timing-columns migration separately would be ceremony with
   no actual upgrade path to walk.
3. **The smoke test fixture invokes alembic via `subprocess`
   rather than the in-process `command.upgrade` API.** Reason:
   in-process alembic on an async engine fights the test event
   loop. The subprocess shape doubles as integration coverage for
   the CI / Fly release-command runner that CP12/CP13 will wire
   up.

Source HEAD is now `b7eed52`. Documentation HEAD advances with
this §5.3 finalize commit.

### Prior workstream — Phase-3a decisions (closed 2026-05-11)

The Phase-3a decision interview (worklog
`docs/worklog/2026-05-11-phase-3a-decisions.md`) settled four of
the seven queued ADRs:

1. **ADR-0018 — Multi-tenancy: per-org + Postgres RLS only.**
   Every user-data table carries `org_id NOT NULL`; RLS policies
   are the sole enforcement; no service-role bypass; operator
   tooling runs through an `admin` role expressed inside RLS.
   Maps cleanly to enterprise self-hosted (single-org).
2. **ADR-0019 — L/A/R retired; L0–L3 kept as plugin capability.**
   The deployment-mode taxonomy disappears. The content-level
   ladder survives as a plugin-manifest `min_content_level`.
   Server-side storage is a **single uniform shape**; no per-user
   retention differentiation in the near term.
3. **ADR-0020 — Auth: per-org token (agent→server) + Anthropic
   credential pass-through (server→Anthropic).** Tokens align
   directly with ADR-0018's per-org RLS context. The server
   **never persists** the user's Anthropic API key — it forwards
   it transiently and discards it after each response stream.
   Zero KMS/Vault build-out; Anthropic-ToS posture is the safest
   available.
4. **ADR-0021 — Plugin manifest signing fully retired.** ADR-0008's
   threat model (user-side `plugin.toml` tampering) disappeared
   with the pivot to server-side plugin execution. The team
   decided not to repurpose signing as a deployment-time trust
   gate (YAGNI for a one-person contributor team). The trust root
   for plugin loading is now the deploy pipeline itself (git +
   CI + server filesystem permissions). Code-removal is a
   separate Phase-3c-prep checkpoint.

**ADRs touched in this workstream**:

- ADR-0018 (new, Accepted) — multi-tenancy boundary.
- ADR-0019 (new, Accepted) — mode-taxonomy fate.
- ADR-0020 (new, Accepted) — auth model.
- ADR-0021 (new, Accepted) — signing fate (supersedes ADR-0008).
- ADR-0008 — status changed to **Superseded by ADR-0021**.
- ADR-0006 — supersession note extended to point at ADR-0019 as
  the ADR that closes its "what survives of L/A/R" open question.

**Where my recommendation differed from the user's pick**: For
ADR-#7 I recommended Option B (repurpose signing as
deployment-time trust). The user picked Option A (full retirement)
on YAGNI grounds. Decision is final; rationale and counter-argument
preserved in `docs/worklog/2026-05-11-phase-3a-decisions.md`
§Decisions.

## Phase 3a — decision ADR queue (4 of 7 settled)

| # | Topic | Status | ADR |
|---|---|---|---|
| 1 | Fallback policy when server unreachable | **Pending** (defers Phase 3b; not on critical path under server-first reframe) | — |
| 2 | Consent + data-handling policy | **Pending** (most blocking remaining item *before any external testing*; operator-only demo not blocked) | — |
| 3 | Agent-to-server auth model | **Settled 2026-05-11** | **ADR-0020** |
| 4 | Local agent language/distribution | **Pending** (defers Phase 3b; not on critical path under server-first reframe) | — |
| 5 | Multi-tenancy boundary | **Settled 2026-05-11** | **ADR-0018** |
| 6 | What survives of ADR-0006 L/A/R modes | **Settled 2026-05-11** | **ADR-0019** |
| 7 | What survives of ADR-0008 signing | **Settled 2026-05-11** — fully retired | **ADR-0021** |

Items 1, 2, 4 do **not** block Phase 3c (server build-out): the
server can be built against ADR-0018/0019/0020 schemas and surfaces
without resolving them. #2 is required before the server is shown
to anyone outside the operator.

## Phase 3c kick-off — deployment platform (2026-05-11)

| Topic | Status | ADR |
|---|---|---|
| Server host + database vendor | **Settled 2026-05-11** | **ADR-0022** |

ADR-0022 commits the project to Fly.io (containerised FastAPI) +
Supabase (managed PostgreSQL with RLS), with `DATABASE_URL` as the
single DB knob and the app shipped as a Dockerfile so the
deployment is not Fly-locked. Reversibility is high — `DATABASE_URL`
swaps the DB, and `fly.toml` is replaced 1:1 by any other
orchestrator's manifest.

---

### Prior workstream — `supabase_sink` (closed 2026-05-08, CP9)

ADR-0007's reference Mode-R plugin is operational against the
operator's real Supabase project (7 rows in `public.exchanges` from
Path 1). All three safety paths verified against real traffic in CP9:

- **Path 1 — Happy** (`Mode R` + opted_in + correct manifest):
  7 rows landed; `request_text` / `response_text` / `usage`
  populated as expected; one row has `model_served=null` (HTTP
  error response from Anthropic — non-SSE body — by-design
  observability hole, see CP9 worklog "Observation").
- **Path 2 — Mode L safety**: `capability_denied` at proxy
  startup, plugin never loaded, 0 new rows, `claude` response
  flowed through the proxy normally. Production equivalent of
  `test_e2e_mode_l_rejects_plugin_at_load_time`.
- **Path 3 — Allowlist mismatch**: manifest's `egress_destinations`
  set to a bogus URL → plugin loaded but `EgressGuard` denied
  every fetch with `reason=destination_not_in_allowlist`; 0 new
  rows; 4 `egress_blocked` audit rows; manifest restored +
  re-signed (ed25519 deterministic → byte-identical to CP8).

> **Note (2026-05-11)**: ADR-0021 retires signing entirely. The
> manifest re-signing path used in CP9 will disappear when the
> code-removal checkpoint lands. The `supabase_sink` plugin itself
> stays valid as a server-side analytics output.

**Workstream artefacts** (per CLAUDE.md §10 public-interface
catalogue):

- ADR-0015 — `EgressClient` Protocol + `EgressResponse` +
  `EgressDenied`; `BasePlugin.egress` / `HookContext.egress`
  reference the *same* per-plugin instance bound at load time.
- ADR-0016 — `LLMTRACK_USER_OPTED_IN` env knob (interim consent
  surface; per-task UX still deferred per ADR-0006 §"Open
  questions").
- New SDK module: `llm_tracker_sdk.egress`.
- New core module: `llm_tracker.egress_guard.client` (`HostEgressClient`).
- New `PluginHost` constructor params: `http_client`,
  `user_opted_in`. New `SHUTDOWN_HOOK_TIMEOUT` = 30 s for sink
  drain.
- New plugin package: `packages/llm_tracker_plugin_supabase_sink/`
  (signed by `minseop`, 55 unit + 3 integration tests).
- Supabase: `public.exchanges` table + RLS enabled (CP4).
- Operator UX: proxy reads `.env` at lifespan; refreshed
  `.env.example` to match the current `Settings` surface.

Closed-checkpoint roll-up (cleanup pass A–G + stop gates +
side-quests):

- A (e2ee4f0): EgressGuard wired into proxy lifespan
- B (3010aae): signature verifier wired + signing CLI
- C (a2bc3d4): on_persisted ordering fix
- D (b1724fa): synthetic SSE block response
- E (2891e8f): audit_log append-only triggers
- F (6a08c9c): ADR-0008 housekeeping
- G (96305e1): session_factory property + ADR-0009
- 14 (654fbfb): ADR-0010 retroactive (Block/Abort.plugin)
- 15 (cfbbb8e): ADR-0011 Transform policy
- 16 (bbb33e7): Transform impl + 4 tests
- 17 (4606ed0): ADR-0012 hook payload routing
- 18 (75ff46a): HookContext impl + 14 tests
- pre-1c verification (2c28f68): TEST-ONLY token_counter + keyword_block
- side-quest #2 (d2e33d5, 9aa8321): `claude-manage` wrapper + async cleanup
- side-quest #3 (0a43502, 161505d): plugin disable config + `/admin/plugins`
- supabase_sink workstream (8712183, f75a841, dff7e3e, a3b5dff,
  9088825, 6ab979c, 4294d10, f420000, f2f53b7, + this CP9
  finalize commit): ADR-0015/0016 + `EgressClient` SDK +
  `LLMTRACK_USER_OPTED_IN` + Supabase schema + the plugin itself
  + `SHUTDOWN_HOOK_TIMEOUT` + signed manifest + `.env` lifespan
  loader + manual e2e

## Phase 1c prerequisites (reframed under ADR-0019)

These three items were Phase-1c carry-overs. **ADR-0019 (2026-05-11)
reframes them server-side**:

- **L2 scrubbed shape of `request_text`**. Scrubber primitives now
  run on the central server, not per user machine. Pinned by
  `test_hook_context.py::test_request_text_returns_body_at_l2_when_ceiling_allows`
  so the eventual change is test-visible. Lands in Phase 3c.
- **Manifest `min_content_level` field** (ADR-0012 §"Open
  questions"). ADR-0019 confirms this primitive survives the
  pivot. Add the schema field + validator + host enforcement
  during Phase 3c. Separate ADR if the host-side semantics surface
  anything non-obvious.
- **Response-side `ctx` accessors** (`response_text`,
  `tool_call_inputs`, etc.). ADR-0012 ships only the request-side
  accessors. Response-side data needs the Phase-2 Extractor to
  surface structured response records first; separate ADR if the
  semantics surface anything non-obvious (e.g. partial vs assembled).

## Next single step

**Phase 3c CP3 — `orgs` + `api_tokens` schema (ADR-0018
substrate).** Third commit of the 14-checkpoint plan at
`docs/worklog/2026-05-11-phase3c-plan.md`:

- New migration
  `packages/llm_tracker_server/alembic/versions/0003_orgs_and_tokens.py`
  adding two tables:
  - `orgs(id UUID PK default gen_random_uuid(), name text NOT NULL,
    created_at timestamptz default now())`.
  - `api_tokens(token_hash text PK, org_id UUID NOT NULL REFERENCES
    orgs(id) ON DELETE CASCADE, name text, created_at timestamptz
    default now(), revoked_at timestamptz)`. Tokens stored hashed
    (SHA-256 hex); plaintext shown once at issuance per ADR-0020.
- Add `Org` and `ApiToken` models to
  `packages/llm_tracker_server/src/llm_tracker_server/storage/models.py`
  using `sqlalchemy.dialects.postgresql.UUID` (or SA-2 `Uuid`) with
  `server_default=text("gen_random_uuid()")`. These are the first
  tables that genuinely want UUID defaults.
- New `tests/test_org_token_models.py` pinning FK + uniqueness
  constraints; same skipif-without-test-DB pattern as the CP2
  smoke test.
- Still **no `org_id` on the four user-data tables, no RLS, no
  auth** — those land in CP4, CP5, CP6.

To revive the dev loop in a new session:

```
docker run -d --name llm-tracker-pg \
  -e POSTGRES_USER=cp2 -e POSTGRES_PASSWORD=cp2 \
  -e POSTGRES_DB=llm_tracker_test \
  -p 55432:5432 postgres:15
export LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test
```

In parallel, the **ADR-#2 consent decision** remains the most
blocking remaining Phase-3a item *before any external testing* of
the central server. Operator-only smoke (CP14) is not blocked.
Legal/privacy input may take longer than internal ADR drafting;
flag to start alongside Phase 3c.

The user-deferred items #1 (fallback) and #4 (agent language) are
**not on the critical path** under the current server-first
reframe; they re-enter the queue once Phase 3b (thin agent) is
ready to start.

## Blocking / decisions needed

- **#2 consent + data-handling**: still owed before *any external
  testing* of the central server. Not blocking the operator-only
  demo path. Legal/privacy review may take longer than internal
  ADR drafting; flag to start in parallel with Phase 3c.
- **#1 fallback** and **#4 agent language**: deferred to Phase 3b
  scoping; not blocking anything Phase 3a or 3c.

## Progress

- [x] Design v0.1 written
- [x] Framework pivot v0.2
- [x] English-only documentation pass
- [x] ADRs 0001–0008 sealed (0004 superseded by 0007)
- [x] Phase 0 — core skeleton (CLOSED 2026-05-04)
- [x] Phase 1a — plugin SDK (CLOSED 2026-05-05)
- [x] Phase 1b — security boundary hardening (CLOSED 2026-05-06)
- [x] Pre-Phase-1c verification — TEST-ONLY plugins (token_counter, keyword_block) (2026-05-06, commit 2c28f68)
- [x] `claude-manage` wrapper — auto-spawn proxy + lifecycle-coupled cleanup (2026-05-07, commits d2e33d5, 9aa8321)
- [x] Plugin disable config + `/admin/plugins` introspection (2026-05-07, commits 0a43502, 161505d)
- [x] **Phase 2 partial — `supabase_sink` reference plugin (CLOSED 2026-05-08, 9 commits 8712183 → CP9 finalize)**
- [x] **Phase 1b loose-ends (CLOSED 2026-05-09, commits 86acecd / 14b6f7a / 86caf03 / 8d4422b)**
- [x] **Architectural pivot to central server documented (2026-05-11, ADR-0017; commits f74710f / 87142f9 / 8a47b2f / fbf23a5)**
- [x] **Phase 3a decisions 4/7 settled (2026-05-11, ADR-0018/0019/0020/0021; commit 223f742)**
- [x] **ADR-0021 code-removal housekeeping (2026-05-11, commit b446c3f)**
- [x] **ADR-0022 deployment platform — Fly.io + Supabase (2026-05-11, commit 3211672)**
- [x] **Phase 3c build plan — 14 commit-sized checkpoints (2026-05-11, commit ec51a40)**
- [x] **Phase 3c CP1 — `llm_tracker_server` skeleton + /healthz (2026-05-11, commit 7d992ff)**
- [x] **Phase 3c CP2 — storage layer on PostgreSQL (2026-05-11, commit b7eed52)**
- [ ] **Phase 3a — remaining 3 decision ADRs** (#1 fallback / #2 consent / #4 agent language)
- [ ] Phase 3b — thin local agent (gated on #1 + #4)
- [ ] Phase 3c — server build-out (2 of 14 checkpoints done; remaining CP3–CP14 per `docs/worklog/2026-05-11-phase3c-plan.md`, anchored on ADR-0018/0019/0020/0022)
- [ ] Phase 1c — `scope_guard` (paused; reframed server-side per ADR-0019; gated on Phase 3c readiness)
- [ ] Phase 3d — carry-overs: OpenAI/Gemini adapters, analytics interface, response-side policy plugins

---

## Update rules (for Claude Code)

At every checkpoint, do these three as one atomic unit (CLAUDE.md §5.3):

1. `git commit` the code change (CLAUDE.md §11).
2. Append the new commit hash to the active worklog's "What was done"
   section, and rewrite the "What's left / Handoff" section as of *now*.
3. Refresh this STATUS.md:
   - Last-updated timestamp (YYYY-MM-DD).
   - Active worklog path.
   - Last 3–5 commits.
   - "Where we paused".
   - "Next single step".

If you don't bundle these three, the next session won't know where to pick
up.
