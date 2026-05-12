# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-12 (Claude Code; Phase 3c CP12 landed — `Dockerfile` + `.dockerignore` at the repo root, multi-stage `python:3.11-slim` image; `docker run` boots `/healthz` 200, HEALTHCHECK reports healthy, image 80.6 MB compressed)
**Updated by**: Claude Code (Phase 3c CP12 checkpoint, source commit 92ddff7)

## Current phase

- **Phase**: **Phase 3c — CP1 + CP2 + CP3 + CP4 + CP5 + CP6 + CP7 +
  CP8 + CP9 + CP10 + CP11 + CP12 closed (12/14).** CP1–CP11
  stand as previously recorded (skeleton, PG storage,
  orgs+api_tokens, `org_id NOT NULL`, RLS + `llm_tracker_app`
  role, auth middleware, Anthropic credential pass-through +
  scrubbing, plugin-host port, org-aware INSERTs, manifest
  `min_content_level` + per-plugin host clamp, `.env.example` +
  `docs/plugins.md` refresh). CP12 turned the server into a
  runnable container: a multi-stage `Dockerfile` (both stages on
  `python:3.11-slim`) at the repo root; the builder pip-installs
  `packages/llm_tracker_sdk` + `packages/llm_tracker_server` +
  `python-ulid` into `/opt/venv`; the runtime stage drops to a
  non-root `app:app` user, copies the venv plus the alembic
  config + scripts under `/app`, exposes `:8080`, runs uvicorn,
  and uses a `python -c urllib.request.urlopen` HEALTHCHECK
  against `/healthz`. A matching `.dockerignore` strips git,
  docs, var, cache directories, every workspace package except
  the sdk + server, and tests inside those two. Verified end-
  to-end on the local Docker daemon: clean build (~60 s on this
  machine), `/healthz` returns `HTTP 200 {"status":"ok","version":
  "0.0.1"}`, Docker HEALTHCHECK transitions `starting → healthy`
  after the first probe, alembic CLI present + driver-wired
  (`alembic --version` → `1.18.4`; `alembic current` reaches
  asyncpg and only fails because no DB is attached). Image:
  80.6 MB compressed registry content / 379 MB on-disk usage —
  the compressed metric (relevant for Fly.io push/pull) is well
  under the plan's "~300 MB" budget, the unpacked metric exceeds
  it by ~26 % and is accepted (see worklog §Decisions §D4).
  Source HEAD now at `92ddff7`.
- **Active task**: **CP13 — `fly.toml` + secrets + staging
  deploy (ADR-0022)** is the queued next commit. **ADR-#2
  consent decision** remains the most blocking remaining
  Phase-3a item before *any external testing*; operator-only
  smoke (CP14) is not blocked.

## Active worklog

`docs/worklog/2026-05-11-phase3c-plan.md` (active; plan-only).
The prior signing-removal worklog
`docs/worklog/2026-05-11-signing-removal.md` is closed.

## Recent commits

```
92ddff7   infra: Dockerfile + .dockerignore for the server (CP12)
ec378fb   docs: STATUS + worklog for Phase 3c CP11 checkpoint
a7e21c9   docs: refresh .env.example + plugins.md for server (CP11)
56a3594   docs: STATUS + worklog for Phase 3c CP10 checkpoint
6c3b7b8   server: per-plugin min_content_level clamp (CP10)
```

## Where we paused

**Phase 3c CP12 — `Dockerfile` + `.dockerignore` — closed.**
The server is now containerised end-to-end on the local Docker
daemon; CP13 wires the same image into Fly.io.

- Created `Dockerfile` at the repo root — multi-stage build,
  both stages on `python:3.11-slim`:
  - **builder**: `python -m venv /opt/venv`; pip-installs
    `packages/llm_tracker_sdk`, `packages/llm_tracker_server`,
    and `python-ulid` into the venv. The SDK + ulid installs are
    explicit workarounds for `packages/llm_tracker_server/
    pyproject.toml` not declaring either today (the code imports
    both; in dev they are provided transitively by `packages/
    llm_tracker/` and uv's workspace pointer). Captured as
    worklog Suggestion #8 along with the stale `uv.lock`
    entry that prevents an in-place fix without a `uv lock`
    refresh.
  - **runtime**: non-root `app:app` user; copies the venv from
    the builder; copies `alembic.ini` + `alembic/` migrations
    under `/app` so the CP13 release-command runner can call
    `alembic upgrade head` against the image as-is (dispatches
    CP11 Suggestion #5); `EXPOSE 8080`; `HEALTHCHECK` uses
    `python -c "urllib.request.urlopen('http://localhost:8080/
    healthz', timeout=3)"` so the slim image doesn't need
    `curl`; final `CMD` is `uvicorn llm_tracker_server.app:app
    --host 0.0.0.0 --port 8080`.
- Created `.dockerignore` at the repo root — strips git, docs,
  var, cache directories, every workspace package except the
  sdk + server, and every `tests/` directory inside the two
  packages that *do* ship. Build context drops to a few MB of
  Python source.
- Removed the initial `# syntax=docker/dockerfile:1.7`
  directive — it forced the Docker daemon to pull the frontend
  image from `registry-1.docker.io`, which failed with a TLS
  handshake timeout on the first build. None of the Dockerfile
  features used here are 1.7-specific; the directive added a
  network dependency for no benefit.

Verification (full transcript in worklog §Verification §CP12):

- `docker build -t llm-tracker-server:cp12 .` — clean build.
  Final layer count: 16; final naming layer DONE in 4.4 s.
- `docker images llm-tracker-server:cp12` reports **80.6 MB
  compressed content / 379 MB unpacked**. The plan's "under
  ~300 MB" budget is met for the compressed registry size
  (the metric for Fly.io push/pull and most production
  targets); on-disk exceeds 300 MB by ~26 % — accepted, see
  worklog §Decisions §D4.
- `docker run -d -p 18080:8080 ... llm-tracker-server:cp12`
  boots in ~2 s. `curl localhost:18080/healthz` returns
  `HTTP 200 {"status":"ok","version":"0.0.1"}`. Structured log
  line `server.startup` shows `auth_wired: false,
  plugin_host_wired: false` — the CP1 boot contract (no DB →
  no auth-gated routes attach) carries through the image.
- Docker `HEALTHCHECK` status: `starting → healthy` after the
  first probe; `docker inspect ... .State.Health.Log` shows
  two consecutive `exit=0` probes.
- `docker exec llm-tracker-cp12-test alembic --version` →
  `alembic 1.18.4`. `alembic current` from `/app` reaches
  asyncpg and fails with `[Errno 111] Connect call failed
  (127.0.0.1, 5432)` — the *informative* part: CLI + driver
  wired correctly; only the DB is missing, which CP13 supplies
  via Fly secrets.

Eight CP12-specific decisions, all flagged in the worklog
§Decisions §CP12; the most load-bearing:

1. **`python-ulid` and `llm-tracker-sdk` installed by the
   Dockerfile, not via a `pyproject.toml` edit.** Surgical
   scope per CLAUDE.md §2.3 + §9, and entangled with a stale
   `uv.lock`. Worklog Suggestion #8 captures the proper
   manifest fix.
2. **`pip install` instead of `uv sync` for the image.** The
   workspace `uv.lock` entry for `llm-tracker-server` has
   `metadata.requires-dist` missing both `typer` and `httpx`
   against the current `pyproject.toml`, so `uv sync --frozen`
   would refuse to install. Plain pip reads the package's
   `pyproject.toml` directly.
3. **Multi-stage with `python:3.11-slim` for both stages.**
   Plan-prescribed base. Non-root `app:app` user added in the
   runtime stage; the builder stays as root for the
   pip-install.
4. **Image size 80.6 MB compressed / 379 MB on-disk;
   accepted.** Reducing further would mean dropping
   `uvicorn[standard]` extras or switching to alpine, both
   larger changes than CP12.
5. **Alembic CLI + `alembic/` + `alembic.ini` ship in the
   runtime image.** Dispatches CP11 Suggestion #5; CP13 can
   run `alembic upgrade head` against the image directly.
6. **`HEALTHCHECK` uses `python -c urllib.request.urlopen`
   instead of `curl`.** Keeps the slim image slim.
7. **Removed the `# syntax=docker/dockerfile:1.7` directive.**
   No 1.7-specific features in use; the directive added a
   network dependency that broke the first build.
8. **Pinned-tag `python:3.11-slim` without a digest.** Hard
   pinning would force manual bumps; flagged as a future CI
   hardening step, not CP12 scope.

Source HEAD is now `92ddff7`. Documentation HEAD advances
with this §5.3 finalize commit.

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

**Phase 3c CP13 — `fly.toml` + secrets + staging deploy
(ADR-0022).** Thirteenth commit of the 14-checkpoint plan at
`docs/worklog/2026-05-11-phase3c-plan.md`:

- `fly.toml` at the repo root declaring the http service,
  internal port 8080, `/healthz` health check, single region
  (`iad`).
- `fly secrets set LLMTRACK_DATABASE_URL=...` against a
  freshly-provisioned Supabase project (pooled connection
  string; enable Supabase's IPv4 add-on if Fly's egress can't
  reach the IPv6 endpoint).
- Decide migration runner: Fly **release command** vs CI step.
  Plan recommends the release command for the demo scale —
  `release_command = "alembic upgrade head"` runs in a one-shot
  ephemeral machine before the rolling deploy, against the same
  image and the same secrets. Per CP12 §Decisions §D5, the
  alembic CLI + `alembic.ini` + `alembic/` migrations already
  ship in the runtime image (`/app/alembic.ini`).
- Provision a demo org + token via the in-image CLI:
  `flyctl ssh console -C 'llm-tracker-server tokens issue
  --org demo'`.
- Verify: `fly deploy` succeeds; `fly status` shows the app
  healthy; `curl https://<app>.fly.dev/healthz` returns 200;
  the `tokens issue` invocation returns a usable bearer token.

Phase-3a dependencies: none for CP13. CP14 (operator-only
end-to-end smoke) follows; it has the soft Phase-3a #2
dependency for *external* testing, but the operator-only
smoke is not blocked.

The CP12 image already builds + runs cleanly on the local
Docker daemon, so the only new mechanics for CP13 are Fly's
manifest (`fly.toml`), the secret push, and the release-command
wiring. Suggestion #8 (manifest gaps in `packages/
llm_tracker_server/pyproject.toml`) can ride alongside or
land independently — it is not gating CP13.

To revive the dev loop in a new session (Postgres on the host
for the test-fixture suite; the Dockerised server is
independent):

```
docker run -d --name llm-tracker-pg \
  -e POSTGRES_USER=cp2 -e POSTGRES_PASSWORD=cp2 \
  -e POSTGRES_DB=llm_tracker_test \
  -p 55432:5432 postgres:15
export LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test
```

To rebuild + smoke the CP12 image in a new session:

```
docker build -t llm-tracker-server:cp12 .
docker run -d --rm -p 18080:8080 --name lts-smoke llm-tracker-server:cp12
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
- [ ] **Phase 3a — remaining 3 decision ADRs** (#1 fallback / #2 consent / #4 agent language)
- [ ] Phase 3b — thin local agent (gated on #1 + #4)
- [ ] Phase 3c — server build-out (12 of 14 checkpoints done; remaining CP13–CP14 per `docs/worklog/2026-05-11-phase3c-plan.md`, anchored on ADR-0017/0018/0019/0020/0022)
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
