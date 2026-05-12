# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-12 (Claude Code; Phase 3c CP7 landed — Anthropic credential pass-through + log scrubbing; 9 new cases green, full repo suite 273 passed with PG / 258 passed without)
**Updated by**: Claude Code (Phase 3c CP7 checkpoint, source commit e1d34bc)

## Current phase

- **Phase**: **Phase 3c — CP1 + CP2 + CP3 + CP4 + CP5 + CP6 + CP7
  closed (7/14).** CP1 brought up the `llm_tracker_server` FastAPI
  skeleton + `/healthz`. CP2 ported the storage layer to PostgreSQL
  (SQLAlchemy async + asyncpg + Alembic env + two migrations).
  CP3 added the ADR-0018 / ADR-0020 tenancy substrate (`orgs` +
  `api_tokens`). CP4 added the column half of defense-in-depth:
  `org_id UUID NOT NULL REFERENCES orgs(id)` on `exchanges`,
  `events`, `tool_calls`, `audit_log`. CP5 added the visibility
  half: migration `0005_rls_policies` creates the non-superuser
  `llm_tracker_app` role, enables and FORCEs RLS on the four
  user-data tables, and lays down two PERMISSIVE policies per table
  (`<table>_org_isolation` + `<table>_admin_access`). CP6 added
  the ADR-0020 Axis-1 edge: a `BaseHTTPMiddleware` parses
  `Authorization: Bearer <token>` (401 on missing/malformed),
  hashes it (SHA-256 hex), looks it up in `api_tokens` filtered to
  non-revoked rows (403 conflated for unknown/revoked), then opens
  a request-scoped session that issues `SET LOCAL ROLE
  llm_tracker_app` + `SELECT set_config('app.org_id', '<uuid>',
  true)` and attaches `request.state.{org_id, session}` for
  downstream handlers. CP7 has now added the ADR-0020 Axis-2 edge:
  a new `proxy/` package whose `forward_request(...)` passes
  `x-api-key` / `anthropic-api-key` through to `api.anthropic.com`
  unchanged while stripping the consumed `Authorization` Bearer,
  and a `scrub_credential_processor` wired into the structlog chain
  that redacts the credential by header-name set *and* by
  `sk-ant-` value-prefix regardless of where it appears in any log
  event. The credential never crosses the persistence boundary:
  no DB column, no log line, no audit row. Source HEAD now at
  `e1d34bc`.
- **Active task**: **CP8 — Port proxy + plugin host server-side
  (ADR-0017 / ADR-0019)** is the queued next commit.
  **ADR-#2 consent decision** remains the most blocking remaining
  Phase-3a item before *any external testing*; operator-only smoke
  (CP14) is not blocked.

## Active worklog

`docs/worklog/2026-05-11-phase3c-plan.md` (active; plan-only).
The prior signing-removal worklog
`docs/worklog/2026-05-11-signing-removal.md` is closed.

## Recent commits

```
e1d34bc   server: add Anthropic credential pass-through + scrubbing (CP7)
a517bcc   docs: STATUS + worklog for Phase 3c CP6 checkpoint
1c0835a   server: add auth middleware + tokens CLI (CP6)
8167e9b   docs: STATUS + worklog for Phase 3c CP5 checkpoint
0dec2f1   server: add RLS policies + app role (CP5)
```

## Where we paused

**Phase 3c CP7 — Anthropic credential pass-through + log scrubbing
— closed.** The server→Anthropic credential edge of ADR-0020
(Axis 2) is now live: every outbound request to `api.anthropic.com`
carries the user's `x-api-key` / `anthropic-api-key` through
unchanged, the llm-tracker Bearer is stripped before the outbound
build (it was already consumed by CP6's middleware and Anthropic
would either reject it or log it), and the structlog chain has the
credential scrubber wired so accidental leakage from any log call
is redacted by both header-name set *and* the `sk-ant-` value-prefix
rule. The credential never crosses the persistence boundary — no
DB column, no log line, no audit row. CP8 will port the full proxy
+ plugin host + SSE Tee from `packages/llm_tracker/` and mount the
catch-all route that calls `forward_request`.

- New `packages/llm_tracker_server/src/llm_tracker_server/proxy/`
  package: `credential.py` declares
  `CREDENTIAL_HEADER_NAMES = {"x-api-key", "anthropic-api-key"}`
  and `scrub_credential_processor`, a structlog processor that
  recursively redacts any value under a credential-header key
  *and* any string value beginning with `sk-ant-` regardless of
  the carrying key; returns a new dict so callers' event payloads
  aren't mutated in place. `forwarder.py` declares
  `forward_request(request, path, *, http_client,
  upstream_base=UPSTREAM_BASE)` — reads inbound body, strips
  hop-by-hop headers + `authorization` (already consumed by CP6),
  builds the outbound httpx request, streams the upstream
  response back; emits a structured `proxy.forward` log with a
  `forwarded_credential` boolean as the audit signal.
  `__init__.py` re-exports the surface and pins CP7's scope:
  credential passthrough only; CP8 owns the catch-all route +
  plugin host port.
- `packages/llm_tracker_server/src/llm_tracker_server/logging.py`
  inserts `scrub_credential_processor` into the structlog chain
  just before the JSON renderer so every emitted event passes
  through the scrubber regardless of which call site wrote it.
- `packages/llm_tracker_server/pyproject.toml` — promoted `httpx`
  from `[dependency-groups] dev` to `[project] dependencies`
  (kept the dev-group entry too; pip/uv de-dupes).
- New `tests/test_credential_passthrough.py` pins nine assertions
  (none require PostgreSQL — the credential surface is DB-free,
  and the forwarder uses `httpx.MockTransport` to capture the
  outbound request):
  - `test_outbound_carries_x_api_key` — inbound `x-api-key`
    reaches the upstream request unchanged.
  - `test_outbound_carries_anthropic_api_key_alternate` — the
    documented alternate name passes through too.
  - `test_outbound_strips_authorization_bearer` — the llm-tracker
    Bearer is *not* forwarded.
  - `test_query_string_is_preserved` — query strings round-trip.
  - Four scrubber unit tests (top-level header keys, nested
    header keys, value-prefix anywhere, no-mutation contract).
  - `test_configured_logging_chain_redacts_credential_from_stdout`
    runs `configure_logging("INFO")`, emits a structured log
    with the credential in three shapes (top-level key, nested
    headers dict, raw value), captures rendered JSON via a
    `StringIO` `StreamHandler`, and asserts the credential bytes
    never appear and the `forwarded_credential` audit signal does.

Verification: targeted run of the new file → **9 passed** in
0.26 s. Full repo suite *without* the test URL → **258 passed,
15 skipped**, 4 warnings (258 = 249 [CP6 baseline] + 9; 15 skips
unchanged from CP6 because CP7 added no PG-dependent test). Full
repo suite *with* the test URL → **273 passed** (264 [CP6] + 9).
Ruff: `check` and `format --check` both clean; one file
(`proxy/forwarder.py`) needed one `ruff format` pass at write
time. App-import smoke with no DB URL still returns a `FastAPI`
object. No `journalctl`/stdout live-port smoke this checkpoint —
the end-to-end stdout test exercises the same code path
(forwarder → outbound httpx → log emission → stdout capture);
the live uvicorn round-trip is deferred to CP14.

Eight CP7-specific decisions, all flagged in the worklog
§Decisions §CP7; the most load-bearing:

1. **`forward_request` takes the `http_client` as an injected
   parameter.** Avoids the module-level lazy singleton the
   local-sidecar forwarder uses (which is what makes its tests
   brittle). Pure-function shape; CP8 will hand it a lifespan-
   scoped client.
2. **The forwarder strips `Authorization` unconditionally.** By
   the time it runs, the only valid value was the consumed
   llm-tracker Bearer; forwarding it would confuse Anthropic or
   leak our token. A future `ANTHROPIC_AUTH_TOKEN` path will be
   re-introduced via a separate header, not by relaxing this rule.
3. **Scrubber matches by header *name* set + value *prefix*.**
   Name set covers the careful logger; `sk-ant-` prefix covers
   the careless one (header `repr()`, stacktrace dumps, generic
   `details=...` keys). Trade-off: prefix is tied to Anthropic's
   current API-key format.
4. **`ANTHROPIC_AUTH_TOKEN` is not a supported configuration in
   CP7.** Our middleware claims the `Authorization` slot. Users
   must use `x-api-key` / `ANTHROPIC_API_KEY` upstream; documented
   in `proxy/credential.py` and surfaces again at CP11.
5. **No DB write, no audit_log row, no `request.state.org_id`
   read in CP7.** The org-aware INSERT wiring is CP9's job;
   bundling them would have mixed two distinct safety properties
   (credential never persisted vs. row org-scoped) into one
   commit and made the later diff harder to audit.
6. **`scrub_credential_processor` returns a new dict.**
   Side-effect-free at the type level; the unit test asserts
   non-mutation as a contract.
7. **No catch-all route wired in CP7.** Plan reads the CP7 file
   list as proxy/__init__.py + forwarder.py + credential.py only;
   wiring the route earlier would have widened every existing
   test's surface. CP8 mounts it once.
8. **httpx promoted to runtime dep.** First runtime requirement;
   dev-group entry intentionally left alongside.

Source HEAD is now `e1d34bc`. Documentation HEAD advances with
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

**Phase 3c CP8 — Port proxy + plugin host server-side
(ADR-0017 / ADR-0019).** Eighth commit of the 14-checkpoint plan at
`docs/worklog/2026-05-11-phase3c-plan.md`:

- Move the FastAPI catch-all route, SSE Tee, hook lifecycle,
  `PluginHost`, `EgressGuard`, and `HookContext` from
  `packages/llm_tracker/src/llm_tracker/` into
  `packages/llm_tracker_server/src/llm_tracker_server/`. Wrap
  CP7's `forward_request` with the plugin-host hook calls
  (`on_request_received`, `before_forward`,
  `on_upstream_response_start`, `on_response_chunk`,
  `on_response_complete`, `on_persisted`), block-response synthesis
  on `Block` / `Abort`, and the synthetic SSE block stream from
  ADR-0002 §3.
- Drop the Mode L/A/R enum and `LLMTRACK_MODE` resolution
  (ADR-0019 §Decision item 1). Drop the `LLMTRACK_USER_OPTED_IN`
  env knob (ADR-0016 superseded by per-org tokens + upcoming
  ADR-#2).
- The local-sidecar `packages/llm_tracker/` package stays in tree
  as historical scaffolding until ADR-#4 (agent language) decides
  Phase 3b.
- Port the Phase 0–1b tests that still apply (capability
  registry, hook dispatcher ordering, content-level routing,
  EgressGuard wiring). Skip the Mode-keyed policy tests retired
  by ADR-0019.

CP7 left two contracts CP8 will rely on:
`forward_request(request, path, *, http_client, upstream_base)`
is the credential-passthrough callable; CP8 mounts it under the
catch-all and threads the `http_client` through `lifespan`. The
structlog chain already has `scrub_credential_processor` wired —
the ported `PluginHost` / `EgressGuard` / hook-lifecycle code
inherits the scrubbing automatically.

CP6 left two contracts CP7 already preserved and CP9 will read:
`request.state.session` is the per-request `AsyncSession` already
bound to `app.org_id` under `llm_tracker_app`, and
`request.state.org_id` is the resolved org UUID. CP9 will read
both when wiring `org_id` onto storage INSERTs (defense in depth
on top of the RLS `WITH CHECK`).

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
- [ ] **Phase 3a — remaining 3 decision ADRs** (#1 fallback / #2 consent / #4 agent language)
- [ ] Phase 3b — thin local agent (gated on #1 + #4)
- [ ] Phase 3c — server build-out (7 of 14 checkpoints done; remaining CP8–CP14 per `docs/worklog/2026-05-11-phase3c-plan.md`, anchored on ADR-0017/0018/0019/0020/0022)
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
