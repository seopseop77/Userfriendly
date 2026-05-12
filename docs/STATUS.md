# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-12 (Claude Code; Phase 3c CP6 landed — auth middleware + tokens CLI; 5 new HTTP cases green, full suite 264 passed)
**Updated by**: Claude Code (Phase 3c CP6 checkpoint, source commit 1c0835a)

## Current phase

- **Phase**: **Phase 3c — CP1 + CP2 + CP3 + CP4 + CP5 + CP6 closed
  (6/14).** CP1 brought up the `llm_tracker_server` FastAPI skeleton
  + `/healthz`. CP2 ported the storage layer to PostgreSQL
  (SQLAlchemy async + asyncpg + Alembic env + two migrations).
  CP3 added the ADR-0018 / ADR-0020 tenancy substrate (`orgs` +
  `api_tokens`). CP4 added the column half of defense-in-depth:
  `org_id UUID NOT NULL REFERENCES orgs(id)` on `exchanges`,
  `events`, `tool_calls`, `audit_log`. CP5 added the visibility
  half: migration `0005_rls_policies` creates the non-superuser
  `llm_tracker_app` role, enables and FORCEs RLS on the four
  user-data tables, and lays down two PERMISSIVE policies per table
  (`<table>_org_isolation` + `<table>_admin_access`). CP6 has now
  added the ADR-0020 Axis-1 edge: a `BaseHTTPMiddleware` parses
  `Authorization: Bearer <token>` (401 on missing/malformed),
  hashes it (SHA-256 hex), looks it up in `api_tokens` filtered to
  non-revoked rows (403 conflated for unknown/revoked), then opens
  a request-scoped session that issues `SET LOCAL ROLE
  llm_tracker_app` + `SELECT set_config('app.org_id', '<uuid>',
  true)` and attaches `request.state.{org_id, session}` for
  downstream handlers. A small `/admin/whoami` route reads the GUC
  back off the same session for the test surface. The Typer
  `llm-tracker-server tokens {issue,revoke,list}` CLI is declared
  as a `[project.scripts]` console script; `tokens issue` prints
  the plaintext exactly once and stores only the SHA-256 hex.
  Source HEAD now at `1c0835a`.
- **Active task**: **CP7 — Anthropic credential pass-through + log
  scrubbing (ADR-0020 Axis 2)** is the queued next commit.
  **ADR-#2 consent decision** remains the most blocking remaining
  Phase-3a item before *any external testing*; operator-only smoke
  (CP14) is not blocked.

## Active worklog

`docs/worklog/2026-05-11-phase3c-plan.md` (active; plan-only).
The prior signing-removal worklog
`docs/worklog/2026-05-11-signing-removal.md` is closed.

## Recent commits

```
1c0835a   server: add auth middleware + tokens CLI (CP6)
8167e9b   docs: STATUS + worklog for Phase 3c CP5 checkpoint
0dec2f1   server: add RLS policies + app role (CP5)
578e8ea   docs: STATUS + worklog for Phase 3c CP4 checkpoint
2da7438   server: add org_id to user-data tables (CP4)
```

## Where we paused

**Phase 3c CP6 — auth middleware + tokens CLI — closed.** The
agent→server identity edge of ADR-0020 is now live: every
authenticated request resolves to a per-org bearer token, drops
into the non-superuser `llm_tracker_app` role, and binds
`app.org_id` for the duration of the request. CP5's RLS policies
have a real caller; CP7 will plug the other ADR-0020 edge (the
Anthropic credential pass-through to `api.anthropic.com`).

- New `packages/llm_tracker_server/src/llm_tracker_server/auth/`
  package: `tokens.py` (SHA-256 hex hashing, `lookup` /
  `issue` / `revoke` / `list_for_org`; plaintext is
  `lts_` + `secrets.token_urlsafe(32)`; `lookup` filters to
  non-revoked rows so callers cannot tell unknown from revoked),
  `middleware.py` (`AuthMiddleware(BaseHTTPMiddleware)` — bypasses
  `/healthz`, parses Bearer, opens one session per request that
  issues `SET LOCAL ROLE llm_tracker_app` then `SELECT
  set_config('app.org_id', '<uuid>', true)` and exposes
  `request.state.{org_id, session}`), `__init__.py` (re-exports
  the surface).
- New `packages/llm_tracker_server/src/llm_tracker_server/cli/`
  package: Typer entry point `app = typer.Typer(...)` with a
  `tokens` subtree of `issue` / `revoke` / `list`. `_session_scope()`
  is a shared async CM that loads `.env`, reads
  `LLMTRACK_DATABASE_URL`, builds an engine + factory, yields a
  session, disposes the engine on exit. `tokens issue` prints
  `org_id=`, `token_hash=`, `token=` on stdout and a "store this
  token now — it cannot be recovered" hint on stderr.
  `cli/__init__.py` is docstring-only; re-exporting `app` would
  trigger a `runpy` warning under `python -m
  llm_tracker_server.cli.main`, and the production console script
  targets `llm_tracker_server.cli.main:app` directly.
- `packages/llm_tracker_server/pyproject.toml` — `typer` added to
  `[project] dependencies`; `[project.scripts]` table introduced
  with `llm-tracker-server = "llm_tracker_server.cli.main:app"`.
- `packages/llm_tracker_server/src/llm_tracker_server/app.py` —
  `create_app(settings=None, session_factory=None)`. If a factory
  is injected, it is used as-is (test path). If `session_factory
  is None` and `settings.database_url` is set, the factory wires
  `make_engine` + `make_session_factory` and disposes the engine
  on lifespan exit. If a factory is available either way, the
  factory registers `AuthMiddleware` and a small `/admin/whoami`
  route that returns `{"org_id": ..., "app_org_id_setting":
  current_setting('app.org_id', true)}` (read off
  `request.state.session`). With no DB URL and no injected
  factory, the app boots `/healthz`-only — the CP1 contract holds.
- `storage/__init__.py` and `storage/models.py` docstrings
  updated to reflect CP6 landing the per-request `SET LOCAL ROLE`
  + `app.org_id` binding (CP9 still owns routing storage INSERTs
  through the same session).
- New `tests/test_auth_middleware.py` pins five HTTP cases:
  missing Authorization → 401; unknown plaintext (never persisted)
  → 403; valid token → 200 with both `org_id` and
  `app_org_id_setting` matching `str(UUID(<assigned id>))`;
  `/healthz` reachable with no Authorization; a revoked token →
  403 with the same body shape as the unknown case.

Verification: PostgreSQL 15.17 container on `localhost:55432`
reused from CP5. Targeted run of the new file: `pytest … -q` →
**5 passed** in 5.79 s. Full suite with test URL: `pytest -q` →
**264 passed**, 4 warnings (23.84 s). Full suite *without* the
test URL → **249 passed, 15 skipped**, 4 warnings (the prior 10
PG smokes plus the 5 new CP6 cases skip; 249 unconditional
passes unchanged from CP5 confirms CP6 did not perturb the non-PG
suite). Ruff: 0 errors after one auto-fix (`RUF022` `__all__`
not-sorted on `auth/__init__.py`); one file (`cli/main.py`)
needed one `ruff format` pass at write time. App-import smoke
with no DB URL still returns a `FastAPI` object. CLI end-to-end
smoke against the docker PG (after `alembic upgrade head`):
`tokens issue --org demo` printed a fresh `org_id`, `token_hash`,
and plaintext; `tokens list --org demo` showed the active row;
`tokens revoke --hash <hash>` returned `revoked`. DB was
downgraded back to base after the smoke.

Seven CP6-specific decisions, all flagged in the worklog
§Decisions §CP6; the most load-bearing:

1. **`create_app` takes an injectable `session_factory`.**
   Production defaults to building one from `settings.database_url`;
   tests inject the CP5 hoisted factory directly so they reuse
   its per-test alembic upgrade/downgrade cycle. With no factory
   and no URL, the app still returns a `/healthz`-only surface —
   the CP1 boot contract still holds.
2. **Unknown and revoked tokens both resolve to a single 403** with
   the same body. Distinguishing them at the response surface would
   let an unauthenticated caller probe whether a plaintext was ever
   issued. `lookup` filters on `revoked_at IS NULL` internally;
   revocation is one `UPDATE`, never a DELETE.
3. **SHA-256 hex, not bcrypt/argon2.** ADR-0020 §"Token issuance"
   pins SHA-256; the plaintext carries ~256 bits of entropy, so a
   slow KDF would buy nothing against the actual threat (DB dump
   recovery). Centralised in `auth.tokens.hash_token` for a future
   migration.
4. **`SET LOCAL ROLE` on every request even though the conftest
   fixture already wraps the test factory with it.** The middleware
   is the production authority; the conftest wrap only makes the
   docker-default superuser look like production for tests.
   `SET LOCAL ROLE` is idempotent within a transaction; running it
   twice is a no-op and the middleware is not allowed to depend on
   a test-only invariant.
5. **`request.state.session` exposed as the per-request session.**
   The plan required `request.state.org_id` only; adding the
   session attribute is what lets `/admin/whoami` read the GUC
   off the same session the middleware bound, which is the
   assertion the test relies on. CP9 will formalise this as the
   storage entry point.
6. **`/admin/whoami` lives in `app.py`** until CP10's
   `/admin/plugins` arrives and earns its own router module.
7. **`lts_` plaintext prefix** is a self-documenting tag for
   operators reading logs; the middleware keys on the SHA-256 hash,
   not the prefix, so format changes don't invalidate existing
   tokens.

Source HEAD is now `1c0835a`. Documentation HEAD advances with
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

**Phase 3c CP7 — Anthropic credential pass-through + log scrubbing
(ADR-0020 Axis 2).** Seventh commit of the 14-checkpoint plan at
`docs/worklog/2026-05-11-phase3c-plan.md`:

- Forward whichever credential header Claude Code natively sends
  (canonically `x-api-key`; confirm during this checkpoint per
  ADR-0020 §Open questions) on the outbound httpx call to
  `api.anthropic.com`. **Never persist**: no DB column, no log
  line, no audit detail. A structlog processor strips the
  credential header from every log entry; a unit test asserts the
  header bytes never appear in a captured log buffer.
- New files under
  `packages/llm_tracker_server/src/llm_tracker_server/proxy/`:
  `__init__.py`, `forwarder.py` (httpx async client + SSE relay;
  port the relevant pieces from
  `packages/llm_tracker/src/llm_tracker/proxy/`),
  `credential.py` (extract on inbound, attach to outbound, scrub
  from logs). `logging.py` gains the scrubbing structlog
  processor.
- New `tests/test_credential_passthrough.py` — assert outbound
  request carries the header; assert no log line ever contains it.

CP6 left two contracts CP7 will rely on: `request.state.session`
is the per-request `AsyncSession` already bound to `app.org_id`
under `llm_tracker_app`, and `request.state.org_id` is the resolved
org UUID. CP9 will read both when wiring `org_id` onto storage
INSERTs (defense in depth on top of the RLS `WITH CHECK`).

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
- [ ] **Phase 3a — remaining 3 decision ADRs** (#1 fallback / #2 consent / #4 agent language)
- [ ] Phase 3b — thin local agent (gated on #1 + #4)
- [ ] Phase 3c — server build-out (6 of 14 checkpoints done; remaining CP7–CP14 per `docs/worklog/2026-05-11-phase3c-plan.md`, anchored on ADR-0018/0019/0020/0022)
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
