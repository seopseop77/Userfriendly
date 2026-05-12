# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-12 (Claude Code; Phase 3c CP9 landed — storage layer org-aware INSERTs; full server suite 55 passed with PG, full repo 287 passed without PG)
**Updated by**: Claude Code (Phase 3c CP9 checkpoint, source commit fe18e9a)

## Current phase

- **Phase**: **Phase 3c — CP1 + CP2 + CP3 + CP4 + CP5 + CP6 + CP7 +
  CP8 + CP9 closed (9/14).** CP1 brought up the
  `llm_tracker_server` FastAPI skeleton + `/healthz`. CP2 ported
  the storage layer to PostgreSQL (SQLAlchemy async + asyncpg +
  Alembic env + two migrations). CP3 added the ADR-0018 /
  ADR-0020 tenancy substrate (`orgs` + `api_tokens`). CP4 added
  the column half of defense-in-depth:
  `org_id UUID NOT NULL REFERENCES orgs(id)` on `exchanges`,
  `events`, `tool_calls`, `audit_log`. CP5 added the visibility
  half: migration `0005_rls_policies` creates the non-superuser
  `llm_tracker_app` role, enables and FORCEs RLS on the four
  user-data tables, and lays down two PERMISSIVE policies per
  table (`<table>_org_isolation` + `<table>_admin_access`). CP6
  added the ADR-0020 Axis-1 edge: a `BaseHTTPMiddleware` parses
  `Authorization: Bearer <token>`, hashes it, looks it up in
  `api_tokens`, and opens a request-scoped session bound to
  `app.org_id` via `SET LOCAL ROLE llm_tracker_app` +
  `set_config('app.org_id', '<uuid>', true)`. CP7 added the
  ADR-0020 Axis-2 edge: `forward_request(...)` passes
  `x-api-key` / `anthropic-api-key` through unchanged while
  stripping the consumed `Authorization` Bearer, and
  `scrub_credential_processor` redacts the credential from any log
  event by header-name set *and* `sk-ant-` value-prefix. CP8
  ported the local-sidecar `PluginHost` + `EgressGuard` +
  `HookContext` lifecycle into `llm_tracker_server`: the catch-all
  `/{path:path}` route wraps CP7's forwarder with the full 8-hook
  plugin lifecycle, the synthetic Anthropic SSE block stream from
  ADR-0002 §3 replaces the upstream body on `Block` / `Abort`,
  and the legacy L/A/R-mode taxonomy (ADR-0019) plus the
  `LLMTRACK_USER_OPTED_IN` env knob (ADR-0016) are gone. CP9 has
  now wired the storage layer to that lifecycle: every `Exchange`
  INSERT lands with `org_id = request.state.org_id` (defense in
  depth on top of CP5's RLS `WITH CHECK`), every audit dispatched
  on a request reaches `audit_log` through a request-scoped
  `ContextVar`-bound writer (`session_bound_audit_writer`), and
  the three `Block` / `Abort` short-circuit paths each persist a
  `blocked_by`-tagged row before returning. Under
  `BaseHTTPMiddleware`'s commit-before-stream ordering, the
  response generator opens a **fresh** `AsyncSession` from
  `app.state.session_factory` for the post-completion timing
  write, re-binding `SET LOCAL ROLE llm_tracker_app` +
  `set_config('app.org_id', ...)` on it before any write. Source
  HEAD now at `fe18e9a`.
- **Active task**: **CP10 — `min_content_level` manifest field +
  host enforcement (ADR-0019 §Open questions)** is the queued
  next commit. **ADR-#2 consent decision** remains the most
  blocking remaining Phase-3a item before *any external testing*;
  operator-only smoke (CP14) is not blocked.

## Active worklog

`docs/worklog/2026-05-11-phase3c-plan.md` (active; plan-only).
The prior signing-removal worklog
`docs/worklog/2026-05-11-signing-removal.md` is closed.

## Recent commits

```
fe18e9a   server: storage layer org-aware INSERTs (CP9)
e9925e1   docs: STATUS + worklog for Phase 3c CP8 checkpoint
79227fe   server: port proxy + plugin host (CP8)
5f069ba   docs: STATUS + worklog for Phase 3c CP7 checkpoint
e1d34bc   server: add Anthropic credential pass-through + scrubbing (CP7)
```

## Where we paused

**Phase 3c CP9 — Storage layer: org-aware INSERTs — closed.**
The CP8 plugin-host lifecycle is now persistence-wired: every
`Exchange` INSERT lands with `org_id = request.state.org_id`,
every audit dispatched on a request reaches `audit_log` through
a request-scoped contextvar-bound writer, and the three short-
circuit paths (`Block` from `on_request_received` /
`before_forward`, `Abort` from `on_upstream_response_start`)
each persist a `blocked_by`-tagged row before returning. CP10
will swap CP8's transitional permissive `HookContext` for
manifest-driven `min_content_level` clamping (ADR-0019 §Open
questions).

- New `packages/llm_tracker_server/src/llm_tracker_server/storage/exchanges.py`
  — `record_exchange_timing` (happy path) +
  `record_exchange_blocked` (short-circuit path). Both helpers
  take `org_id` keyword-only and set it on the column
  explicitly; both `flush` — not `commit` — so the per-request
  session retains transaction control.
- New `packages/llm_tracker_server/src/llm_tracker_server/storage/audit.py`
  — `write_audit(session, *, org_id, kind, ...)`. The
  append-only triggers from migration `0002_audit_log_triggers`
  make each flushed row permanent once the request transaction
  commits.
- New `packages/llm_tracker_server/src/llm_tracker_server/audit_context.py`
  — `bind_request_context(session, org_id)` is a sync `with`
  setting a `ContextVar`; `session_bound_audit_writer(**kwargs)`
  reads the contextvar and forwards to `write_audit`, no-opping
  outside a request scope (lifecycle audits are a deferred
  Phase-3c carry-over).
- Modified `packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py`
  — `forward_request` reads `request.state.session` +
  `request.state.org_id`, wraps the pre-streaming hook calls in
  `bind_request_context`, and inserts a `record_exchange_blocked`
  call before each of the three `block_response(...)` returns.
  The response generator opens a **fresh** `AsyncSession` from
  `request.app.state.session_factory` (under
  `BaseHTTPMiddleware` the auth session is committed and
  closed before the body iterates), re-issues `SET LOCAL ROLE
  llm_tracker_app` + `set_config('app.org_id', ...)` on it,
  binds the contextvar to the fresh session, calls
  `record_exchange_timing` between `on_response_complete` and
  `on_persisted`, then `commit`s. Both lifecycle paths fold
  into one `AsyncExitStack`. The CP7/CP8 transparent shape
  survives byte-for-byte (gated on
  `has_post_stream_storage`).
- Modified `packages/llm_tracker_server/src/llm_tracker_server/app.py`
  — lifespan constructs `EgressGuard` + `PluginHost` with
  `audit_writer=session_bound_audit_writer` and stashes
  `app.state.session_factory` so the forwarder generator can
  open the fresh post-stream session.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/storage/__init__.py`
  to re-export the three new helpers.
- New `tests/test_two_org_e2e_isolation.py` (1 case,
  PG-required) — `test_two_org_e2e_isolation` seeds two orgs +
  tokens, drives a real POST `/v1/messages` through the
  catch-all as org A (upstream mocked via
  `httpx.MockTransport` + `monkeypatch` on
  `forwarder.UPSTREAM_BASE`), then asserts: as org A → 1 row
  with `org_id = org_A`, `endpoint = "v1/messages"`,
  `blocked_by IS NULL`; as org B → 0 rows; as `app.role =
  'admin'` → 1 row total.

Verification: server test suite (no PG) → **39 passed, 16
skipped** (CP8 baseline 39 / 15 + 1 new CP9 e2e test that
requires PG). Server test suite with PG → **55 passed** (39
no-PG + 16 PG-gated, all green). Full repo suite without PG →
**287 passed, 16 skipped, 4 warnings** (CP8 baseline 287 / 15 +
the new CP9 e2e test counted as skipped here). Ruff `check` +
`format --check` clean on the server package; pre-existing
lint/format drift in adjacent packages left untouched per
CLAUDE.md §2.3 surgical-changes.

Nine CP9-specific decisions, all flagged in the worklog
§Decisions §CP9; the most load-bearing:

1. **Generator opens a fresh `AsyncSession` for post-stream
   writes.** Under `BaseHTTPMiddleware`, the auth middleware's
   `session.commit()` runs before the outer ASGI iterates the
   body, so `request.state.session` is closed by the time the
   generator's `record_exchange_timing` would fire. The
   plan's "use the same session" letter is unachievable with
   the current middleware shape; the split (middleware session
   pre-stream, fresh session post-stream) is the workaround. A
   pure-ASGI replacement of `AuthMiddleware` is the long-term
   fix and is now flagged as a CP9.5 housekeeping ticket.
2. **Audit writer wired through a `ContextVar`.** Per-request
   `PluginHost.audit_writer` overrides would race under
   concurrency; the contextvar binds `(session, org_id)` for
   the duration of each `with bind_request_context(...)` block.
3. **`record_exchange_*` / `write_audit` flush, not commit.**
   The per-request session keeps transaction control so the
   middleware's terminal `commit()` is still the single commit
   point pre-stream; the generator owns the commit on its fresh
   session post-stream.
4. **Storage helpers mirror local-sidecar file names
   (`exchanges.py` + `audit.py`).** The plan's
   `events.py` + `tool_calls.py` files don't exist yet because
   the Phase-2 extractor hasn't been built; no helper modules
   are introduced that nobody calls.
5. **`session_factory` plumbed onto `app.state`.** Same seam
   used by `upstream_client` + `plugin_host`. Forwarder reads
   it via `request.scope.get("app")` so unit tests that build
   a bare `Request` still hit the transparent path.
6. **`session_bound_audit_writer` is a free function.** Free
   functions with module-level state compose more cleanly with
   both `PluginHost` and `EgressGuard` than a singleton.
7. **`SET LOCAL ROLE` + `set_config` issued unconditionally
   on the fresh session.** Production needs both; tests need
   only the GUC (conftest wraps the role drop); idempotent on
   the same transaction.
8. **Lifecycle audits silently dropped.** No org context
   outside a request + NOT NULL `audit_log.org_id` + no
   service-role bypass = no row written. The call sites stay
   in place so ADR-#2 / a follow-up checkpoint can light them
   up under whatever shape it picks (operator-org, system-org,
   separate table).
9. **CP9 e2e test bypasses FastAPI lifespan.** Seeds
   `app.state` (`upstream_client`, `plugin_host`,
   `session_factory`) manually instead of paying for a real
   `httpx.AsyncClient` lifecycle per test.

Source HEAD is now `fe18e9a`. Documentation HEAD advances with
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

**Phase 3c CP10 — `min_content_level` manifest field + host
enforcement (ADR-0019 §Open questions).** Tenth commit of the
14-checkpoint plan at `docs/worklog/2026-05-11-phase3c-plan.md`:

- Add `min_content_level` to the plugin manifest schema
  (default `L3`; valid values `L0` / `L1` / `L2` / `L3`).
- Server-side `PluginHost.make_hook_context` clamps each
  plugin's `HookContext` view to the declared level — a plugin
  asking for `L0` cannot reach `request_text` even when the
  data is in memory.
- Drop the mode-keyed intersection logic still living in the
  SDK's `HookContext`: CP8's transitional shape passes
  `mode="R"` + `user_opted_in=True` which the SDK resolves to
  L3. Either thread `min_content_level` into the SDK or
  replace the shim with the declared level directly.
- New test `tests/test_min_content_level.py`: declare a plugin
  at L1, assert it cannot access `request_text`; declare
  another at L3, assert it can.
- `/admin/plugins` payload gets `min_content_level` so
  manifests remain self-describing through introspection
  (ADR-0014).

CP9 left two contracts CP10 will rely on:

- The CP8 transitional permissive `HookContext` is still in
  place: `make_hook_context` returns L3 visibility for every
  plugin. CP10's job is to replace that with manifest-driven
  clamping. Existing test
  `test_begin_exchange_passes_same_ctx_to_each_hook` pins the
  current L3-visible behaviour and needs a sibling pinning the
  new clamping shape.
- `PluginHost.loaded_plugins()` already serialises
  `allowed_modes`; CP10 adds `min_content_level` to the same
  payload.

The CP9 storage + audit wiring stays as-is — CP10 doesn't
change INSERT shapes. The two-session split (middleware
pre-stream, fresh session post-stream; CP9 §D1) is a CP9.5
housekeeping ticket and is not on CP10's path.

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
- [x] **Phase 3c CP6 — auth middleware + tokens CLI (2026-05-12, commit 1c0835a)**
- [x] **Phase 3c CP7 — Anthropic credential pass-through + log scrubbing (2026-05-12, commit e1d34bc)**
- [x] **Phase 3c CP8 — Port proxy + plugin host server-side (2026-05-12, commit 79227fe)**
- [x] **Phase 3c CP9 — Storage layer: org-aware INSERTs (2026-05-12, commit fe18e9a)**
- [ ] **Phase 3a — remaining 3 decision ADRs** (#1 fallback / #2 consent / #4 agent language)
- [ ] Phase 3b — thin local agent (gated on #1 + #4)
- [ ] Phase 3c — server build-out (9 of 14 checkpoints done; remaining CP10–CP14 per `docs/worklog/2026-05-11-phase3c-plan.md`, anchored on ADR-0017/0018/0019/0020/0022)
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
