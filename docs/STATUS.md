# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-12 (Claude Code; Phase 3c CP11 landed — `.env.example` + `docs/plugins.md` refresh against the server's actual surface; docs-only, no test delta)
**Updated by**: Claude Code (Phase 3c CP11 checkpoint, source commit a7e21c9)

## Current phase

- **Phase**: **Phase 3c — CP1 + CP2 + CP3 + CP4 + CP5 + CP6 + CP7 +
  CP8 + CP9 + CP10 + CP11 closed (11/14).** CP1–CP10 stand as
  previously recorded (skeleton, PG storage, orgs+api_tokens,
  `org_id NOT NULL`, RLS + `llm_tracker_app` role, auth
  middleware, Anthropic credential pass-through + scrubbing,
  plugin-host port, org-aware INSERTs, manifest `min_content_level`
  + per-plugin host clamp). CP11 was the documentation pass before
  containerisation: `.env.example` was rewritten against the
  server's actual surface (the only env vars the server reads are
  `LLMTRACK_DATABASE_URL`, `LLMTRACK_LOG_LEVEL`, and
  `LLMTRACK_TEST_DATABASE_URL` for the PG smoke tests) and every
  retired knob (`LLMTRACK_MODE`, `LLMTRACK_USER_OPTED_IN`, SQLite
  path, sidecar host/port, supabase_sink env) was removed. The
  per-request bearer token (ADR-0020 Axis 1) and the Anthropic
  credential pass-through (Axis 2) are now documented as
  informational headers — they are inbound HTTP, not env-driven.
  `docs/plugins.md` was updated for CP10: the manifest schema
  section gained a `min_content_level` entry, the §3.1 ceiling
  table was rewritten from mode-keyed to manifest-keyed (with the
  legacy mode/opt-in math kept as a fallback paragraph for the
  local-sidecar `packages/llm_tracker/` package), and §9
  ("Mode-aware behavior") was retitled "(legacy)" with an
  explanation of what replaced it. A new §12 "Running locally —
  server-side load path" documents the entry-point group
  (`llm_tracker.plugins`), manifest discovery + audit shape, the
  per-plugin ceiling clamp, and a worked local-dev loop. No code
  files changed; no test delta. Source HEAD now at `a7e21c9`.
- **Active task**: **CP12 — `Dockerfile` (ADR-0022)** is the queued
  next commit. **ADR-#2 consent decision** remains the most
  blocking remaining Phase-3a item before *any external testing*;
  operator-only smoke (CP14) is not blocked.

## Active worklog

`docs/worklog/2026-05-11-phase3c-plan.md` (active; plan-only).
The prior signing-removal worklog
`docs/worklog/2026-05-11-signing-removal.md` is closed.

## Recent commits

```
a7e21c9   docs: refresh .env.example + plugins.md for server (CP11)
56a3594   docs: STATUS + worklog for Phase 3c CP10 checkpoint
6c3b7b8   server: per-plugin min_content_level clamp (CP10)
dc6a983   docs: STATUS + worklog for Phase 3c CP9 checkpoint
fe18e9a   server: storage layer org-aware INSERTs (CP9)
```

## Where we paused

**Phase 3c CP11 — `.env.example` + developer docs refresh —
closed.** Documentation pass before containerisation. No
Python files changed; the operator-facing surface is now
consistent with the code shipped at CP1–CP10.

- Rewrote `.env.example` against the server's actual surface
  (`packages/llm_tracker_server/src/llm_tracker_server/config.py`).
  The three env vars the server reads —
  `LLMTRACK_DATABASE_URL` (storage), `LLMTRACK_LOG_LEVEL`
  (structlog), `LLMTRACK_TEST_DATABASE_URL` (PG-gated test
  fixtures) — are now the only environment-driven knobs in the
  file. The per-org bearer token (ADR-0020 Axis 1) and the
  Anthropic credential pass-through (Axis 2) are documented as
  *informational* — they are inbound HTTP headers handled by
  `AuthMiddleware` and `proxy/credential.py`, not env-driven.
  `ANTHROPIC_BASE_URL` is retained as the only client-side
  knob the example influences.
- Removed every retired knob: `LLMTRACK_MODE` (ADR-0019),
  `LLMTRACK_USER_OPTED_IN` (ADR-0016 retired), sidecar host/port,
  SQLite path, supabase_sink env namespace,
  `LLMTRACK_PLUGINS_DISABLED` (constructor kwarg exists but is
  not wired from env in `app.py` — listing it would be a
  doc-vs-code lie).
- Modified `docs/plugins.md`:
  - §2 schema gained `min_content_level = "L3"` with commentary
    on the default + opt-down semantics (CP10).
  - §3.1 ceiling table rewritten from a deployment-mode-keyed
    matrix to a manifest-`min_content_level`-keyed matrix. The
    legacy `effective_ceiling(mode, user_opted_in=...)` math is
    demoted to a one-paragraph fallback note, mirroring the
    SDK's runtime fallback shape introduced in CP10.
  - §9 retitled "Mode-aware behavior (legacy)": `allowed_modes`
    is parsed and surfaces through `/admin/plugins` for
    backward-compat but no longer gates load; what a plugin
    can see is `min_content_level`, what it can reach is
    `egress_destinations`.
  - New §12 "Running locally — server-side load path": the
    `llm_tracker.plugins` entry-point group,
    `importlib.metadata.entry_points` scan, manifest discovery
    + `manifest_rejected` audit shape, CP10's
    `_bind_plugin_view` per-plugin ceiling clamp +
    `HostEgressClient` binding, and a worked local-dev loop
    (`docker run postgres:15` → `alembic upgrade head` →
    `uvicorn` → `llm-tracker-server tokens issue --org demo`).
- Did **not** touch `docs/plugins.md §8` (stale "EgressGuard
  arrives in Phase 1b" wording) — out of CP11 scope per
  CLAUDE.md §2.3 surgical-changes; logged as Suggestion #7 in
  the worklog.

Verification: `grep -nE 'LLMTRACK_MODE|LLMTRACK_USER_OPTED_IN|
sqlite|LLMTRACK_PLUGIN_SUPABASE_SINK|LLMTRACK_PROXY_HOST|
LLMTRACK_PROXY_PORT|LLMTRACK_DB_URL='` on `.env.example`
returns empty. `python -c "from llm_tracker_server.app import
app; ..."` boots without `LLMTRACK_DATABASE_URL` and exposes
`/openapi.json` + `/healthz` (the CP1 boot contract — no DB →
no auth-gated routes attach). Ruff `check` + `format --check`
clean on `packages/llm_tracker_sdk` and
`packages/llm_tracker_server`. No new tests; the change
surface is documentation only.

Seven CP11-specific decisions, all flagged in the worklog
§Decisions §CP11; the most load-bearing:

1. **Per-request headers stay informational in `.env.example`,
   not env vars.** The bearer token and Anthropic credential
   are inbound HTTP headers; the server reads them from
   `Request.headers`, not `Settings`. Putting them in
   `.env.example` as `LLMTRACK_*` would mislead operators.
2. **Omitted `LLMTRACK_PLUGINS_DISABLED`.** The constructor
   kwarg exists but is not wired from `Settings` in `app.py`.
   Documenting it would be a doc-vs-code lie; wiring it
   through is a separate ticket.
3. **`.env.example` retains `ANTHROPIC_BASE_URL`** under a
   labelled "Claude Code wiring" block. It is the only env
   var on the client side that the example influences.
4. **`docs/plugins.md §3.1` ceiling table replaced wholesale,
   not layered.** The pre-CP10 table was keyed on retired
   surfaces (mode + opt-in flag); layering would leave two
   competing primary surfaces in the document.
5. **§9 retitled "Mode-aware behavior (legacy)" instead of
   deleted.** `allowed_modes` is still parsed and surfaces
   through `/admin/plugins`; renaming + explaining what
   replaced it keeps the field discoverable without dropping
   it from the reference manifest.
6. **New §12 lives at the end of `plugins.md`, not woven into
   §5.** §1–§11 follow a plugin-author flow; server-side load
   path content is operator-facing.
7. **Did not sweep §8's stale "Phase 1b" wording.** Out of
   CP11 scope per CLAUDE.md §2.3; logged as Suggestion #7.

Source HEAD is now `a7e21c9`. Documentation HEAD advances with
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

**Phase 3c CP12 — `Dockerfile` (ADR-0022).** Twelfth commit of
the 14-checkpoint plan at
`docs/worklog/2026-05-11-phase3c-plan.md`:

- Multi-stage `Dockerfile` at the repo root. Base
  `python:3.11-slim`; build stage installs
  `packages/llm_tracker_server` + its deps; runtime stage
  copies the venv and runs `uvicorn llm_tracker_server.app:app
  --host 0.0.0.0 --port 8080`. Healthcheck hits `/healthz`.
- `.dockerignore` at the repo root to keep the image small.
- Per worklog Suggestion #5: ship the `alembic` CLI in the
  runtime image so CP13's release-command migration runner
  does not trip on a missing entry point.
- Verify: `docker build -t llm-tracker-server .` succeeds;
  `docker run -e LLMTRACK_DATABASE_URL=... -p 8080:8080
  llm-tracker-server` boots; `curl localhost:8080/healthz`
  returns 200; final image under ~300 MB.

Phase-3a dependencies: none for CP12. CP13 (Fly + secrets +
staging) and CP14 (operator-only end-to-end smoke) follow;
CP14 has the soft Phase-3a #2 dependency for *external*
testing, but the operator-only smoke is not blocked.

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
- [x] **Phase 3c CP10 — `min_content_level` manifest field + per-plugin host clamp (2026-05-12, commit 6c3b7b8)**
- [x] **Phase 3c CP11 — `.env.example` + developer docs refresh (2026-05-12, commit a7e21c9)**
- [ ] **Phase 3a — remaining 3 decision ADRs** (#1 fallback / #2 consent / #4 agent language)
- [ ] Phase 3b — thin local agent (gated on #1 + #4)
- [ ] Phase 3c — server build-out (11 of 14 checkpoints done; remaining CP12–CP14 per `docs/worklog/2026-05-11-phase3c-plan.md`, anchored on ADR-0017/0018/0019/0020/0022)
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
