# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-13 (Claude Code; Phase 3c CP13-b landed — operator ran `docs/deploy.md` end-to-end against real Fly.io + Supabase. First deploy hit two failures (stale `public.exchanges` from the closed `supabase_sink` workstream; asyncpg / pgbouncer transaction-mode prepared-statement clash), both diagnosed and resolved. Server is live at `https://llm-tracker-server.fly.dev/` with alembic head = `0005_rls_policies`; two `nrt` Machines passing `/healthz`. One source-code commit shipped to make the deploy stick. **CP14 (operator-only smoke) is the only remaining Phase 3c plan-checkpoint.**)
**Updated by**: Claude Code (Phase 3c CP13-b checkpoint, source commit 3050bcc)

## Current phase

- **Phase**: **Phase 3c — CP1 through CP13 closed (13/14
  plan-checkpoints).** CP1–CP12 stand as previously recorded
  (skeleton, PG storage, orgs+api_tokens, `org_id NOT NULL`,
  RLS + `llm_tracker_app` role, auth middleware, Anthropic
  credential pass-through + scrubbing, plugin-host port,
  org-aware INSERTs, manifest `min_content_level` + per-plugin
  host clamp, `.env.example` + `docs/plugins.md` refresh,
  multi-stage Dockerfile + `.dockerignore`). CP13-a (file-only
  half) shipped `fly.toml` at the repo root + `docs/deploy.md`
  runbook (commits `ef59192` + `59dbae6`). **CP13-b (this
  checkpoint) ran the runbook against real Fly.io + Supabase**;
  two real-world failures surfaced and were fixed in flight:
  (i) the operator's Supabase project still carried a
  stale-schema `public.exchanges` (7 rows) from the closed
  Phase-2 `supabase_sink` plugin workstream — dropped via
  Supabase MCP `execute_sql` after confirming no other stale
  objects (no `alembic_version`, no `audit_log_reject_modify`
  function); (ii) once migrations applied cleanly, follow-up
  commands like `alembic current` and any DB-touching app route
  failed with `asyncpg.DuplicatePreparedStatementError` against
  Supabase's pgbouncer transaction-mode pooler — fixed by
  passing `connect_args={"statement_cache_size": 0}` through
  both `make_engine()` and `alembic/env.py` (commit `3050bcc`).
  Server is live at `https://llm-tracker-server.fly.dev/`,
  alembic head = `0005_rls_policies`, RLS on for the four
  user-data tables, two `nrt` Machines passing `/healthz`.
- **Active task**: **CP14 — operator-only end-to-end smoke**
  (mint demo bearer token via `fly ssh console -C
  "llm-tracker-server tokens issue --org demo"`, send one real
  `/v1/messages` request with a valid Anthropic `x-api-key`,
  verify stream round-trip, one row in `public.exchanges`
  scoped to demo org, no traceback in `fly logs`). **ADR-#2
  consent decision** remains the most blocking remaining
  Phase-3a item before *any external testing*; operator-only
  smoke (CP14) is not blocked.

## Active worklog

`docs/worklog/2026-05-13-cp13b-fly-deploy.md` (closes CP13-b).
`docs/worklog/2026-05-11-phase3c-plan.md` remains the plan-of-record
across the rest of Phase 3c.

## Recent commits

```
3050bcc   server: pgbouncer transaction-mode compat (CP13-b)
90d29f3   docs: STATUS + worklog for Phase 3c CP13-a checkpoint
59dbae6   docs: Fly.io + Supabase deploy guide (CP13-b)
ef59192   infra: fly.toml for the server (CP13-a)
a8b622b   docs: STATUS + worklog for Phase 3c CP12 checkpoint
```

## Where we paused

**Phase 3c CP13-b — first Fly.io + Supabase deploy — closed.**
The operator drove `docs/deploy.md` end-to-end. Two real-world
failures surfaced in flight and were fixed inside this session:

- **Failure 1: stale `public.exchanges` from the closed
  `supabase_sink` workstream.** The operator's Supabase project
  was the same one used by the Phase-2 `supabase_sink` plugin
  (closed 2026-05-08), which had created `public.exchanges` with
  an *incompatible* schema (`exchange_id` PK, `ts_started_ms`,
  `mode`, `source`, `request_text/response_text/raw_*`). The new
  server's `0001_initial_schema` collided
  (`DuplicateTableError: relation "exchanges" already exists`)
  on first `fly deploy`. Diagnosis confirmed via Supabase MCP
  `list_tables` (single stale table, 7 rows, no `alembic_version`
  yet, no trigger function) — i.e. nothing of the new schema had
  partially applied. Dropped the stale table via MCP
  `execute_sql DROP TABLE public.exchanges CASCADE` after
  confirming with the user that ADR-0007's plugin data is not
  load-bearing (ADR-0017 supersedes ADR-0007; the plugin's
  `schema.sql` is checked in so a future revival can rebuild a
  fresh sink target without depending on these rows). Second
  `fly deploy` ran `alembic upgrade head` cleanly through 0001
  → 0005; both `nrt` Machines passed `/healthz`.
- **Failure 2: asyncpg / pgbouncer transaction-mode prepared-
  statement clash.** After migrations applied, `alembic current`
  (and any DB-touching application route) failed with
  `asyncpg.exceptions.DuplicatePreparedStatementError: prepared
  statement "__asyncpg_stmt_1__" already exists`. Cause: Supabase's
  pooled URL (Transaction mode pgbouncer) does not preserve
  prepared statement names across pooled sessions, while asyncpg
  caches them by default. Fix shipped in commit `3050bcc`
  (`server: pgbouncer transaction-mode compat (CP13-b)`):
  `connect_args={"statement_cache_size": 0}` passed through both
  `make_engine()` and `alembic/env.py` `create_async_engine`.
  No-op against direct PG (the local Docker test fixture); the
  single-token-of-effect lives in `make_engine` so it covers the
  server, the `llm-tracker-server tokens issue` CLI, and the test
  fixtures uniformly. Initial false-start (also passing
  `prepared_statement_cache_size=0` as a top-level kwarg) was
  reverted — that is a URL-level dialect parameter, not an
  engine kwarg, and the root-cause error name (`__asyncpg_stmt_N__`)
  pointed at asyncpg's cache only.

Verification (post-deploy, full transcript in worklog
§Verification):

```
$ fly ssh console -C "alembic current"
0005_rls_policies (head)

$ curl -i https://llm-tracker-server.fly.dev/healthz
HTTP/2 200 ...
{"status":"ok","version":"0.0.1"}

$ for i in 1 2 3; do curl -s -o /dev/null -w "HTTP %{http_code}\n" \
   -X POST https://llm-tracker-server.fly.dev/v1/messages \
   -H "Content-Type: application/json" \
   -d '{"model":"claude-opus-4-5","max_tokens":1,"messages":[]}'; done
HTTP 401   HTTP 401   HTTP 401
```

Supabase schema state (via MCP `list_tables`, post-deploy):

```
public.alembic_version  (1 row, version_num = 0005_rls_policies)
public.exchanges        (RLS on,  0 rows)
public.events           (RLS on,  0 rows)
public.tool_calls       (RLS on,  0 rows)
public.audit_log        (RLS on,  0 rows)
public.orgs             (RLS off — substrate, by design 0005)
public.api_tokens       (RLS off — substrate, by design 0005)
```

CP13-b-specific decisions captured in the worklog
`docs/worklog/2026-05-13-cp13b-fly-deploy.md` §Decisions; the
load-bearing ones:

1. **Same Supabase project, drop the stale plugin table.** Plugin
   workstream is closed; rows are not load-bearing; spinning up
   a new Supabase project would have doubled secrets + budget for
   no benefit.
2. **Disable asyncpg's prepared-statement cache at the engine
   layer**, not via URL query parameter. Single point of effect
   across all callers; portable across deploy environments;
   `LLMTRACK_DATABASE_URL` secret stays untouched.
3. **Did not also disable SQLAlchemy's compiled prepared-statement
   cache.** The reproducible failure was asyncpg's
   `__asyncpg_stmt_N__` only; verified by three consecutive
   `/v1/messages` 401s post-fix.
4. **Did not auto-apply the Supabase RLS advisor remediation SQL.**
   Advisor flagged `alembic_version`, `orgs`, `api_tokens` as
   RLS-disabled. `alembic_version` is alembic-internal;
   `orgs`/`api_tokens` are *intentionally* RLS-disabled per the
   0005 docstring (tenancy substrate the auth path needs to read
   before any RLS context is set). The advisor's concern is
   PostgREST-anon exposure — not used by this server, but a
   defense-in-depth follow-up CP is owed (REVOKE anon/authenticated
   or RLS-with-`llm_tracker_app`-only policy). Surfaced; not
   acted on.

Source HEAD is now `3050bcc`. Documentation HEAD advances with
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

**Phase 3c CP14 — operator-only end-to-end smoke.** The server is
already live at `https://llm-tracker-server.fly.dev/` (CP13-b
closed); CP14 sends the first real `/v1/messages` request through
it.

1. **Mint the demo bearer token** (once; output is shown only at
   issuance time):

   ```
   fly ssh console -C "llm-tracker-server tokens issue --org demo"
   ```

   Save the printed plaintext token. The server stores only the
   SHA-256 hash; this string cannot be recovered later.
2. **Send one real `/v1/messages`** request to the deployed server
   with a valid Anthropic API key in `x-api-key` and the demo
   token in `Authorization`. The body should be a real, non-empty
   `messages` payload (anything trivial that Anthropic will
   answer; `claude-opus-4-5` works).
3. **Verify three things, in order:**
   - The response stream returns to the client unchanged (the
     SSE wire bytes match what Anthropic emitted, modulo the
     final `event: message_stop`).
   - Exactly one row lands in `public.exchanges` scoped to the
     demo org (`SELECT * FROM exchanges` via Supabase MCP / SQL
     editor; the row's `org_id` matches `SELECT id FROM orgs
     WHERE name = 'demo'`).
   - `fly logs` (since the request timestamp) shows no traceback
     — the path covers auth middleware → credential
     pass-through → plugin host → org-aware INSERT.

CP14 is closed when those three pass. After CP14, Phase 3c's
14-checkpoint plan is fully closed and Phase 3c overall flips
to "closed (operator smoke validated)". External-tester flavours
of CP14 require **ADR-#2 (consent + data handling)** to settle
first.

The asyncpg / pgbouncer compat fix shipped in `3050bcc` should
be re-verified under CP14's authenticated load — auth middleware
reads `api_tokens` on *every* request, which is the exact code
path that triggered the original
`DuplicatePreparedStatementError` and the place where any
remaining cache pathology would resurface.

To revive the local dev loop in a new session (Postgres on the
host for the test-fixture suite; the Dockerised server +
Fly.io deployment are independent):

```
docker run -d --name llm-tracker-pg \
  -e POSTGRES_USER=cp2 -e POSTGRES_PASSWORD=cp2 \
  -e POSTGRES_DB=llm_tracker_test \
  -p 55432:5432 postgres:15
export LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test
```

To rebuild + smoke the CP12 image locally:

```
docker build -t llm-tracker-server:local .
docker run -d --rm -p 18080:8080 --name lts-smoke llm-tracker-server:local
curl -sS http://localhost:18080/healthz
docker stop lts-smoke
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
- [x] **Phase 3c CP6 — auth middleware + tokens CLI (2026-05-12, commit 1c0835a)**
- [x] **Phase 3c CP7 — Anthropic credential pass-through + log scrubbing (2026-05-12, commit e1d34bc)**
- [x] **Phase 3c CP8 — Port proxy + plugin host server-side (2026-05-12, commit 79227fe)**
- [x] **Phase 3c CP9 — Storage layer: org-aware INSERTs (2026-05-12, commit fe18e9a)**
- [x] **Phase 3c CP10 — `min_content_level` manifest field + per-plugin host clamp (2026-05-12, commit 6c3b7b8)**
- [x] **Phase 3c CP11 — `.env.example` + developer docs refresh (2026-05-12, commit a7e21c9)**
- [x] **Phase 3c CP12 — `Dockerfile` + `.dockerignore` (2026-05-12, commit 92ddff7)**
- [x] **Phase 3c CP13-a — `fly.toml` + `docs/deploy.md` (2026-05-13, commits ef59192 + 59dbae6)**
- [x] **Phase 3c CP13-b — first Fly.io + Supabase deploy (2026-05-13, commit 3050bcc; server live at `https://llm-tracker-server.fly.dev/`)**
- [ ] **Phase 3a — remaining 3 decision ADRs** (#1 fallback / #2 consent / #4 agent language)
- [ ] Phase 3b — thin local agent (gated on #1 + #4)
- [ ] Phase 3c — server build-out (13 of 14 plan-checkpoints done; CP14 remaining — operator-only end-to-end smoke. Plan at `docs/worklog/2026-05-11-phase3c-plan.md`, anchored on ADR-0017/0018/0019/0020/0022)
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
