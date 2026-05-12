# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-12 (Claude Code; Phase 3c CP8 landed — proxy + plugin host server-side port; 29 new cases green, full repo suite 287 passed without PG)
**Updated by**: Claude Code (Phase 3c CP8 checkpoint, source commit 79227fe)

## Current phase

- **Phase**: **Phase 3c — CP1 + CP2 + CP3 + CP4 + CP5 + CP6 + CP7 +
  CP8 closed (8/14).** CP1 brought up the `llm_tracker_server`
  FastAPI skeleton + `/healthz`. CP2 ported the storage layer to
  PostgreSQL (SQLAlchemy async + asyncpg + Alembic env + two
  migrations). CP3 added the ADR-0018 / ADR-0020 tenancy substrate
  (`orgs` + `api_tokens`). CP4 added the column half of
  defense-in-depth: `org_id UUID NOT NULL REFERENCES orgs(id)` on
  `exchanges`, `events`, `tool_calls`, `audit_log`. CP5 added the
  visibility half: migration `0005_rls_policies` creates the
  non-superuser `llm_tracker_app` role, enables and FORCEs RLS on
  the four user-data tables, and lays down two PERMISSIVE policies
  per table (`<table>_org_isolation` + `<table>_admin_access`).
  CP6 added the ADR-0020 Axis-1 edge: a `BaseHTTPMiddleware`
  parses `Authorization: Bearer <token>`, hashes it, looks it up
  in `api_tokens`, and opens a request-scoped session bound to
  `app.org_id` via `SET LOCAL ROLE llm_tracker_app` +
  `set_config('app.org_id', '<uuid>', true)`. CP7 added the
  ADR-0020 Axis-2 edge: `forward_request(...)` passes
  `x-api-key` / `anthropic-api-key` through unchanged while
  stripping the consumed `Authorization` Bearer, and
  `scrub_credential_processor` redacts the credential from any log
  event by header-name set *and* `sk-ant-` value-prefix. CP8 has
  now ported the local-sidecar `PluginHost` + `EgressGuard` +
  `HookContext` lifecycle into `llm_tracker_server`: the catch-all
  `/{path:path}` route wraps CP7's forwarder with the full 8-hook
  plugin lifecycle, the synthetic Anthropic SSE block stream from
  ADR-0002 §3 replaces the upstream body on `Block` / `Abort`, and
  the legacy L/A/R-mode taxonomy (ADR-0019) plus the
  `LLMTRACK_USER_OPTED_IN` env knob (ADR-0016) are gone. Audit
  writes are routed through an injected callable (CP9 wires the
  session-bound writer). Source HEAD now at `79227fe`.
- **Active task**: **CP9 — Storage layer: org-aware INSERTs
  (ADR-0018 + ADR-0020 wiring)** is the queued next commit.
  **ADR-#2 consent decision** remains the most blocking remaining
  Phase-3a item before *any external testing*; operator-only smoke
  (CP14) is not blocked.

## Active worklog

`docs/worklog/2026-05-11-phase3c-plan.md` (active; plan-only).
The prior signing-removal worklog
`docs/worklog/2026-05-11-signing-removal.md` is closed.

## Recent commits

```
79227fe   server: port proxy + plugin host (CP8)
5f069ba   docs: STATUS + worklog for Phase 3c CP7 checkpoint
e1d34bc   server: add Anthropic credential pass-through + scrubbing (CP7)
a517bcc   docs: STATUS + worklog for Phase 3c CP6 checkpoint
1c0835a   server: add auth middleware + tokens CLI (CP6)
```

## Where we paused

**Phase 3c CP8 — Port proxy + plugin host server-side — closed.**
The catch-all `/{path:path}` route now wraps CP7's credential-
passthrough forwarder with the full 8-hook plugin lifecycle, the
synthetic Anthropic SSE block stream from ADR-0002 §3 replaces the
upstream body on `Block` / `Abort` decisions, and the legacy
L/A/R-mode taxonomy (ADR-0019) plus the `LLMTRACK_USER_OPTED_IN`
env knob (ADR-0016) are gone. CP9 will wire the storage writes
(`record_exchange_timing` / `record_exchange_blocked` / audit-row
emission) through the per-request session so every INSERT carries
`org_id = request.state.org_id`.

- New `packages/llm_tracker_server/src/llm_tracker_server/plugin_host/`
  package (4 modules + `__init__.py`):
  - `host.py` — `PluginHost` ported from the local sidecar with
    `mode=`, `user_opted_in=`, and `session_factory=` dropped.
    Audit writes route through an injected `AuditWriter`
    callable (no-op default; CP9 swaps in a session-bound
    writer). Entry-point loading, manifest validation,
    `plugins_disabled` denylist (ADR-0013), per-plugin
    `HostEgressClient` wiring (ADR-0015), timeout + exception
    isolation, and `loaded_plugins()` introspection (ADR-0014)
    are all preserved.
  - `context.py` — `make_hook_context(...)` is the single
    chokepoint for per-exchange `HookContext` construction.
    Passes `mode="R"` + `user_opted_in=True` to the SDK
    dataclass (yielding L3 visibility) as a transitional shape;
    CP10's `min_content_level` manifest field will introduce
    per-plugin clamping.
  - `manifest.py` — `find_manifest(plugin_class)` walks
    `importlib.resources` for the plugin's top-level package
    and parses `plugin.toml`. `allowed_modes` passes validation
    but is ignored by the host (ADR-0019).
  - `hooks.py` — `HOOK_TIMEOUT = 5.0`,
    `SHUTDOWN_HOOK_TIMEOUT = 30.0` (the supabase_sink carry-over
    so a sink drain doesn't fault under the 5 s per-exchange
    budget).
- New `packages/llm_tracker_server/src/llm_tracker_server/egress_guard/`
  package (`guard.py` + `client.py` + `__init__.py`):
  - `guard.py` — `EgressGuard` ported with `mode=` dropped and
    the three mode-keyed denial paths
    (`mode_L_denies_egress`, `mode_X_not_in_allowed_modes`,
    `mode_A_requires_single_destination`) removed. What remains:
    manifest registration, capability declaration check,
    exact-URL allowlist. Audit writes via injected `AuditWriter`.
  - `client.py` — `HostEgressClient` ported verbatim (ADR-0015
    is untouched by ADR-0019).
- New `packages/llm_tracker_server/src/llm_tracker_server/content_levels/`
  package — re-export of the SDK content-level primitives.
- New `packages/llm_tracker_server/src/llm_tracker_server/proxy/sse.py`
  — `block_sse_chunks(reason, exchange_id)` returns the exact
  Anthropic SSE byte sequence (`message_start` →
  `content_block_start` → `content_block_delta` with
  `[llm-tracker] <reason>` → `content_block_stop` →
  `message_delta` → `message_stop`); `block_response(...)` wraps
  it as a `StreamingResponse` whose `gen()` finally-clause runs
  `plugin_host.end_exchange(...)` so per-exchange ctx is dropped
  on every block / abort path.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py`
  — `plugin_host` is a new keyword-only argument; when supplied,
  `forward_request` runs the full lifecycle around the upstream
  call: `begin_exchange` → `on_request_received` (`Block`
  short-circuits) → `before_forward` (`Block` / `Transform`
  honoured) → `on_upstream_response_start` (`Abort` honoured) →
  per-chunk `on_response_chunk` (`Abort` cuts mid-stream) → on a
  clean upstream EOF, `on_response_complete` + `on_persisted` →
  `end_exchange` in the generator's outer finally. The
  `async for ... else` idiom gates the completion hooks so a
  truncated stream doesn't fire them (this fixes a pre-existing
  control-flow flaw in the local sidecar). `plugin_host=None`
  preserves the CP7 transparent shape byte-for-byte.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/app.py`
  — `lifespan` owns two `httpx.AsyncClient` instances (upstream
  forwarding + plugin egress; mirrors the local-sidecar split so
  the egress client outlives `on_shutdown` for a drain), builds
  an `EgressGuard` + `PluginHost`, attaches them to
  `app.state`. Two new routes mounted when the session factory
  is available: `/admin/plugins` (ADR-0014) and the catch-all
  `@app.api_route("/{path:path}", methods=[DELETE/GET/PATCH/POST/PUT])`
  that calls `forward_request(...)` with the lifespan-owned
  upstream client and the `plugin_host`. The bare `/healthz`
  boot contract from CP1 is preserved.
- Modified `proxy/__init__.py` to re-export the new SSE pieces.
- New `tests/test_plugin_host.py` (15 cases, no PG fixture) —
  ported from the local sidecar with the audit-row assertions
  swapped to a list-capturing writer; covers lifecycle audit
  emissions, fault isolation, shutdown-budget headroom, manifest
  validation, egress wiring, ADR-0019 mode retirement,
  disable-by-config, introspection, and HookContext propagation.
- New `tests/test_egress_guard.py` (7 cases, no PG) — ports the
  denial + allow paths without the mode-keyed variants.
- New `tests/test_proxy_forwarder_hooks.py` (7 cases, no PG) —
  integration coverage for `Block` / `Transform` / `Abort` at
  each hook plus the happy-path dispatch order.

Verification: server test suite → **39 passed, 15 skipped** (15
new plugin_host + 7 new egress_guard + 7 new forwarder hooks +
10 existing CP7/healthz; 15 skipped because no PG locally). Full
repo suite without PG → **287 passed, 15 skipped, 4 warnings**
(258 [CP7 baseline] + 29 new = 287). Ruff `check` + `format
--check` clean. App-import smoke (`from llm_tracker_server.app
import app`) still returns a `FastAPI` object with no DB URL.

Eleven CP8-specific decisions, all flagged in the worklog
§Decisions §CP8; the most load-bearing:

1. **Permissive-by-default `HookContext` is transitional.**
   `make_hook_context` passes `mode="R"` + `user_opted_in=True`
   so the SDK resolves to L3 until CP10's manifest clamping
   lands.
2. **`LLMTRACK_USER_OPTED_IN` retired.** Per-org tokens (CP6)
   are the new identity anchor; ADR-#2 will set the consent
   surface.
3. **`EgressGuard` no longer mode-gates anything.** Only the
   manifest's own declarations enforce egress now.
4. **Audit writes routed through an injected `AuditWriter`
   callable.** Lets CP9 swap in a request-scoped, org-tagged
   writer without changing any call site in `host.py`.
5. **Storage writes deferred to CP9.** The forwarder hands the
   plugin host the timing values via `on_response_complete` but
   writes nothing to the DB itself.
6. **`policy.py` (mode-keyed capability denial) not ported.**
   ADR-0019 retired the underlying enforcement.
7. **`async for ... else` fix in the forwarder.** Truncated
   streams no longer misleadingly fire the completion hooks
   (pre-existing flaw in the local-sidecar version).
8. **No new `proxy/app.py` module.** Catch-all + lifespan
   wiring live in the existing top-level `app.py`.
9. **Two `httpx.AsyncClient` instances in `lifespan`.** Forwarder
   client (`http2=False`) and egress client (defaults) have
   independent lifecycles so the egress client outlives the
   plugin shutdown drain.
10. **Catch-all gated on auth middleware.** Without
    `LLMTRACK_DATABASE_URL` the catch-all is not registered;
    `/healthz` still works without a DB.
11. **`BaseHTTPMiddleware` shape of `AuthMiddleware` preserved.**
    A pure-ASGI rewrite was out of scope; CP14 smoke will
    reveal whether streaming through it actually breaks SSE.

Source HEAD is now `79227fe`. Documentation HEAD advances with
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

**Phase 3c CP9 — Storage layer: org-aware INSERTs
(ADR-0018 + ADR-0020 wiring).** Ninth commit of the 14-checkpoint
plan at `docs/worklog/2026-05-11-phase3c-plan.md`:

- Every INSERT path in the ported storage layer (`exchanges`,
  `events`, `tool_calls`, `audit_log`) writes
  `org_id = request.state.org_id`. The same per-request
  `AsyncSession` (bound by CP6's middleware to `app.org_id` via
  `SET LOCAL ROLE llm_tracker_app` +
  `set_config('app.org_id', :uuid, true)`) is the one CP9
  uses for the writes, so RLS sees the matching org axis.
  Defense in depth: the column is set explicitly even though
  RLS would block a wrong-org write.
- Swap the `PluginHost`'s no-op `audit_writer` (CP8 default)
  for a session-bound writer that takes the request-scoped
  session + `request.state.org_id` and writes an `AuditLog`
  row. Every call site in `host.py` (load events, lifecycle
  audits, `hook_invoked`, `plugin_fault`) routes through this
  writer; CP9 doesn't need to touch the host file.
- In the forwarder's `generate()`: inside the existing
  `if completed and plugin_host is not None` block, call
  `record_exchange_timing` (or a CP9-renamed equivalent) with
  the locally-held timing values + `org_id` before firing
  `on_persisted`. The `Block` path return calls
  `record_exchange_blocked` first so the row carries
  `blocked_by = result.plugin` + the org id.
- Add a two-org end-to-end isolation test through the real
  `/v1/messages` path: issue a request as org A, assert the
  exchange row in org B's session-scope is invisible.

CP8 left three contracts CP9 will rely on:

- `PluginHost(audit_writer=...)` is the swap-in point for a
  session-bound writer.
- The forwarder's `generate()` already holds `t0_mono`,
  `t0_epoch_ms`, and the `timing` dict for CP9 to read.
- The `Block` path's call site in `forward_request` is the
  insertion point for `record_exchange_blocked`.

CP6 left two contracts CP9 still reads:
`request.state.session` is the per-request `AsyncSession`
bound to `app.org_id`, and `request.state.org_id` is the
resolved org UUID.

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
- [ ] **Phase 3a — remaining 3 decision ADRs** (#1 fallback / #2 consent / #4 agent language)
- [ ] Phase 3b — thin local agent (gated on #1 + #4)
- [ ] Phase 3c — server build-out (8 of 14 checkpoints done; remaining CP9–CP14 per `docs/worklog/2026-05-11-phase3c-plan.md`, anchored on ADR-0017/0018/0019/0020/0022)
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
