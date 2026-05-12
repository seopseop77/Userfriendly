# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-12 (Claude Code; Phase 3c CP5 landed — RLS policies + `llm_tracker_app` role; 10 PG smoke tests green)
**Updated by**: Claude Code (Phase 3c CP5 checkpoint, source commit 0dec2f1)

## Current phase

- **Phase**: **Phase 3c — CP1 + CP2 + CP3 + CP4 + CP5 closed (5/14).**
  CP1 brought up the `llm_tracker_server` FastAPI skeleton +
  `/healthz`. CP2 ported the storage layer to PostgreSQL
  (SQLAlchemy async + asyncpg + Alembic env + two migrations).
  CP3 added the ADR-0018 / ADR-0020 tenancy substrate (`orgs` +
  `api_tokens`). CP4 added the column half of defense-in-depth:
  `org_id UUID NOT NULL REFERENCES orgs(id)` on `exchanges`,
  `events`, `tool_calls`, `audit_log`. CP5 has now added the
  visibility half: migration `0005_rls_policies` creates the
  non-superuser `llm_tracker_app` role (so the docker-default
  superuser can't bypass), enables and FORCEs RLS on the four
  user-data tables, and lays down two PERMISSIVE policies per
  table — `<table>_org_isolation` (keyed on
  `current_setting('app.org_id', true)`) and `<table>_admin_access`
  (keyed on `app.role`). The `conftest.py` fixture was hoisted out
  of three copy-pasted bodies and now wraps each session with
  `SET LOCAL ROLE llm_tracker_app`. A new
  `test_rls_two_org_isolation.py` pins org A insert → org B sees
  zero rows → org A back → admin cross-org → unbound default-closed,
  plus a negative path where an org-A session cannot WITH CHECK a
  row claiming `org_id = B`. Source HEAD now at `0dec2f1`.
- **Active task**: **CP6 — auth middleware (ADR-0020 Axis 1)** is the
  queued next commit. **ADR-#2 consent decision** remains the most
  blocking remaining Phase-3a item before *any external testing*;
  operator-only smoke (CP14) is not blocked.

## Active worklog

`docs/worklog/2026-05-11-phase3c-plan.md` (active; plan-only).
The prior signing-removal worklog
`docs/worklog/2026-05-11-signing-removal.md` is closed.

## Recent commits

```
0dec2f1   server: add RLS policies + app role (CP5)
578e8ea   docs: STATUS + worklog for Phase 3c CP4 checkpoint
2da7438   server: add org_id to user-data tables (CP4)
dd3bded   docs: STATUS + worklog for Phase 3c CP3 checkpoint
373ed11   server: add orgs + api_tokens schema (CP3)
```

## Where we paused

**Phase 3c CP5 — RLS policies + `llm_tracker_app` role — closed.**
ADR-0018's visibility half of defense-in-depth now lives on the
four user-data tables. The column half (CP4) and the visibility
half (CP5) together close the per-org tenancy boundary at the
schema level. CP6 will sit a FastAPI auth middleware on top that
issues the per-request invocation the policies expect.

- New migration
  `packages/llm_tracker_server/alembic/versions/0005_rls_policies.py`
  does three things in order: (1) `CREATE ROLE llm_tracker_app
  NOLOGIN` (guarded `DO $$ IF NOT EXISTS`) + `GRANT USAGE` on
  schema + CRUD on the six tables it needs to touch; (2)
  `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` on
  `exchanges`, `events`, `tool_calls`, `audit_log`; (3) for each
  of those four tables, two PERMISSIVE policies — `<table>_org_isolation`
  (`org_id = NULLIF(current_setting('app.org_id', true), '')::uuid`
  on both USING and WITH CHECK) and `<table>_admin_access`
  (`NULLIF(current_setting('app.role', true), '') = 'admin'` on
  both clauses). The `NULLIF` wrap is the fix for a Postgres
  quirk: once a custom GUC has been set in any earlier
  transaction, `current_setting(..., true)` returns `''` (not
  NULL) in later transactions where it is unset, which would
  raise `invalid input syntax for type uuid` and break the
  default-closed assertion.
- `packages/llm_tracker_server/src/llm_tracker_server/storage/__init__.py`
  docstring updated to reflect CP5 landing the RLS half; CP6 still
  owns the per-request `SET LOCAL app.org_id`.
- New `packages/llm_tracker_server/tests/conftest.py` hoists the
  three copy-pasted `_run_alembic` + `session_factory` fixtures
  from CP2/CP3/CP4 into one shared file. The hoisted fixture
  additionally wraps the raw SQLAlchemy sessionmaker in an async
  context manager that issues `SET LOCAL ROLE llm_tracker_app` on
  every session — without that wrap, the docker-default
  `POSTGRES_USER=cp2` superuser would bypass RLS unconditionally
  (`FORCE ROW LEVEL SECURITY` alone is not enough against
  superusers).
- New `tests/test_rls_two_org_isolation.py` pins five visibility
  assertions plus one write-path assertion:
  - `test_two_org_isolation` — bound to org A, insert 2
    exchanges; bound to org B, `SELECT count(*)` returns 0; bound
    back to A, count = 2; admin (no `app.org_id`, `app.role =
    'admin'`), count = 2; unbound, count = 0 (default-closed).
  - `test_cross_org_write_rejected` — bound to org A, attempting
    to insert a row with `org_id = B` raises
    `sa.exc.ProgrammingError` with `row-level security` in the
    message.
- CP2's `tests/test_storage_smoke.py` updated: both round-trip
  and append-only tests now `SELECT set_config('app.org_id', :v,
  true)` after the Org flush, before writing to a user-data
  table. CP4's `tests/test_org_id_constraint.py` updated: each
  test runs under `set_config('app.role', 'admin', true)` so the
  admin policy branch admits the WITH CHECK and column-level
  constraints (NOT NULL, FK) still surface as `IntegrityError`.
  CP3's `tests/test_org_token_models.py` updated only at the
  import / fixture surface — `orgs` and `api_tokens` have no RLS,
  so no per-test GUC is needed.

Verification: PostgreSQL 15.17 container on `localhost:55432`
reused from CP4. Targeted PG-only run (the new isolation file +
the three CP2/CP3/CP4 PG smokes): `pytest … -q` → **10 passed**
in 11.98 s. Full suite with test URL: `pytest -q` → **259 passed**,
4 warnings (19.50 s). Full suite *without* the test URL →
**249 passed, 10 skipped**, 4 warnings (the 2 CP2 + 4 CP3 + 2 CP4
+ 2 CP5 PG smokes skip; the four `fork()` warnings from
`cli/manage.py` are unchanged). Ruff: 0 errors; 17 files
formatted; the two new files needed one `ruff format` pass at
write time. Offline alembic SQL preview captured in the worklog
§Verification §CP5 — `CREATE ROLE` + `GRANT` + 4 × (`ENABLE` +
`FORCE` + two policies).

Seven CP5-specific decisions, all flagged in the worklog
§Decisions §CP5; the most load-bearing:

1. **Non-superuser app role created inside the migration**, not
   left as a deployment-time step. `FORCE ROW LEVEL SECURITY`
   alone is not enough — superusers bypass RLS unconditionally —
   so without a role-drop the docker-default `cp2` test
   connection would never have RLS apply. Baking the role into
   the schema also makes the test environment look like
   production.
2. **`NULLIF(current_setting(name, true), '')`** in every policy
   clause, not the bare cast in the plan. Closes the empty-string
   quirk that surfaced as the first-run failure of
   `test_two_org_isolation` (recorded in §Verification §CP5
   "First-attempt failures").
3. **Two PERMISSIVE policies per table** rather than one combined
   CASE policy. `pg_policies` reads more cleanly — admin is
   visibly a separate enforcement path, not a clause buried
   inside another.
4. **Admin branch is `FOR ALL`**, not `FOR SELECT` as the plan
   prose suggested. Symmetric with the per-org policy and matches
   the shape CP6+ admin tooling will want; can be tightened in a
   one-statement future migration.
5. **`conftest.py` hoist resolved Suggestion #6.** Hoisted the
   alembic subprocess + session factory and additionally wrapped
   the factory to issue `SET LOCAL ROLE llm_tracker_app` on every
   session. Per-org seeding stayed in the RLS test file — pushing
   it into the fixture would over-fit a shared surface to one
   caller.
6. **`FORCE ROW LEVEL SECURITY` kept** even though tests now use
   a non-owner role. Belt-and-braces for a future deploy where
   the app role is also the schema owner.
7. **Skip-cause decorators retained** alongside the fixture-side
   `pytest.skip()`. The decorator fires before fixture setup, so
   a developer without PG never sees the `_run_alembic` error.

Source HEAD is now `0dec2f1`. Documentation HEAD advances with
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

**Phase 3c CP6 — auth middleware (ADR-0020 Axis 1).** Sixth commit
of the 14-checkpoint plan at
`docs/worklog/2026-05-11-phase3c-plan.md`:

- New FastAPI middleware that reads `Authorization: Bearer <tok>`,
  hashes the token (SHA-256 hex), looks it up in `api_tokens`,
  sets `request.state.org_id`, and issues the CP5-shaped
  `SET LOCAL ROLE llm_tracker_app` + `SET LOCAL app.org_id =
  '<uuid>'` pair on the per-request DB transaction. 401 on
  missing/malformed Authorization, 403 on unknown/revoked token.
- New `llm-tracker-server tokens {issue,revoke,list}` Typer CLI
  (`pyproject.toml` adds `typer` + console-script entry).
  `tokens issue` prints the plaintext once and stores only the
  hash, per ADR-0020 §"Token issuance".
- New `tests/test_auth_middleware.py` — three cases: missing
  Authorization → 401; unknown token → 403; valid token →
  `request.state.org_id` is set and the downstream handler reads
  the correct `app.org_id` via `current_setting`. The CP5-hoisted
  `session_factory` fixture is the right base; CP6's middleware
  essentially performs the same role-drop + GUC-set that the
  fixture's wrapper performs, so the test asserts the
  middleware's behaviour by reading `current_setting('app.org_id')`
  from inside the handler under test.
- **No service-role bypass**: ADR-0018 §Decision item 2 + the CP5
  worklog §Decisions §CP5 first bullet together close that door.
  Admin tooling, when it arrives in CP10+, sets `app.role =
  'admin'` alongside `app.org_id`; it does NOT skip the role drop.

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
- [x] **Phase 3c CP3 — orgs + api_tokens substrate (2026-05-11, commit 373ed11)**
- [x] **Phase 3c CP4 — `org_id NOT NULL` on user-data tables (2026-05-11, commit 2da7438)**
- [x] **Phase 3c CP5 — RLS policies + `llm_tracker_app` role (2026-05-12, commit 0dec2f1)**
- [ ] **Phase 3a — remaining 3 decision ADRs** (#1 fallback / #2 consent / #4 agent language)
- [ ] Phase 3b — thin local agent (gated on #1 + #4)
- [ ] Phase 3c — server build-out (5 of 14 checkpoints done; remaining CP6–CP14 per `docs/worklog/2026-05-11-phase3c-plan.md`, anchored on ADR-0018/0019/0020/0022)
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
