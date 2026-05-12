# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-12 (Claude Code; Phase 3c CP10 landed — `min_content_level` manifest field + per-plugin host clamp; full server suite 60 passed with PG, full repo 292 passed without PG)
**Updated by**: Claude Code (Phase 3c CP10 checkpoint, source commit 6c3b7b8)

## Current phase

- **Phase**: **Phase 3c — CP1 + CP2 + CP3 + CP4 + CP5 + CP6 + CP7 +
  CP8 + CP9 + CP10 closed (10/14).** CP1–CP9 stand as previously
  recorded (skeleton, PG storage, orgs+api_tokens, `org_id NOT
  NULL`, RLS + `llm_tracker_app` role, auth middleware, Anthropic
  credential pass-through + scrubbing, plugin-host port, org-aware
  INSERTs). CP10 has now made the plugin-visibility ceiling
  manifest-driven: every `PluginManifest` carries a
  `min_content_level` field (default `L3`; valid `L0` / `L1` /
  `L2` / `L3`, parsed from TOML as strings), the SDK's
  `HookContext` gained an optional `_ceiling` slot that wins over
  the legacy mode/opt-in math when present, and the server-side
  `PluginHost` re-points `ctx._ceiling` per plugin via a new
  `_bind_plugin_view(ctx, plugin)` helper before every hook
  dispatch. An L1 plugin can no longer reach `request_text` even
  when the data is in memory; the L1 escape hatch
  (`request_hash` + `request_length`) still resolves. The legacy
  mode-keyed table (`effective_ceiling(mode, user_opted_in=...)`)
  is preserved in the SDK as the fallback path so the
  local-sidecar `packages/llm_tracker/` callers and their tests
  do not regress. `/admin/plugins` (ADR-0014) now reports each
  plugin's declared level alongside `allowed_modes`, serialised
  as the enum's name (e.g. `"L3"`). Source HEAD now at `6c3b7b8`.
- **Active task**: **CP11 — `.env.example` + developer docs
  refresh** is the queued next commit. **ADR-#2 consent
  decision** remains the most blocking remaining Phase-3a item
  before *any external testing*; operator-only smoke (CP14) is
  not blocked.

## Active worklog

`docs/worklog/2026-05-11-phase3c-plan.md` (active; plan-only).
The prior signing-removal worklog
`docs/worklog/2026-05-11-signing-removal.md` is closed.

## Recent commits

```
6c3b7b8   server: per-plugin min_content_level clamp (CP10)
dc6a983   docs: STATUS + worklog for Phase 3c CP9 checkpoint
fe18e9a   server: storage layer org-aware INSERTs (CP9)
e9925e1   docs: STATUS + worklog for Phase 3c CP8 checkpoint
79227fe   server: port proxy + plugin host (CP8)
```

## Where we paused

**Phase 3c CP10 — `min_content_level` manifest field + host
enforcement — closed.** CP8's transitional permissive
`HookContext` shape is gone. Every plugin manifest now carries
a `min_content_level` (default `L3`; declared in TOML as
`"L0"` / `"L1"` / `"L2"` / `"L3"`), and the server-side
`PluginHost` re-points `ctx._ceiling` per plugin via a new
`_bind_plugin_view(ctx, plugin)` helper before every hook
dispatch. An L1 plugin can no longer reach `request_text` even
when the data is in memory; the L1 escape hatch
(`request_hash` + `request_length`) still resolves. The SDK's
legacy mode/opt-in ceiling math (`effective_ceiling(mode,
user_opted_in=...)`) is preserved as the fallback path so the
local-sidecar `packages/llm_tracker/` package and its tests do
not regress.

- Modified `packages/llm_tracker_sdk/src/llm_tracker_sdk/manifest.py`
  — `PluginManifest` gains
  `min_content_level: ContentLevel = ContentLevel.L3` plus a
  `mode="before"` field validator that accepts strings, ints, and
  the enum itself; unknown values raise with the ladder
  enumeration.
- Modified `packages/llm_tracker_sdk/src/llm_tracker_sdk/hook_context.py`
  — `HookContext` gains optional
  `_ceiling: ContentLevel | None = None`;
  `effective_ceiling()` prefers `_ceiling` when present and
  falls back to the legacy mode/opt-in table otherwise.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/plugin_host/context.py`
  — `make_hook_context` accepts an optional
  `min_content_level` keyword and threads it to
  `HookContext._ceiling`; placeholder `mode="R"` /
  `user_opted_in=True` are now inert filler.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/plugin_host/host.py`
  — adds `self._min_levels: dict[str, ContentLevel]` populated
  during `load_plugins`; new `_bind_plugin_view(ctx, plugin)`
  helper sets `ctx.egress` + `ctx._ceiling` per plugin before
  every per-exchange dispatcher's `_call`; `loaded_plugins()`
  payload now includes `"min_content_level": m.min_content_level.name`.
- Modified `packages/llm_tracker_server/tests/test_plugin_host.py`
  — `test_loaded_plugins_returns_serialisable_view` expected
  dict gains the new `"min_content_level": "L3"` field.
- New `packages/llm_tracker_server/tests/test_min_content_level.py`
  (5 cases, no PG): per-plugin L1 vs L3 visibility through a
  shared exchange context, `loaded_plugins()` payload
  reporting, default-L3 manifest, and unknown-level validation
  error.

Verification: server test suite (no PG) → **44 passed, 16
skipped** (CP9 baseline 39 / 16 + 5 new CP10 cases). Server
test suite with PG → **60 passed** (44 no-PG + 16 PG-gated,
all green; CP9 baseline 55). Full repo suite without PG →
**292 passed, 16 skipped, 4 warnings** (CP9 baseline 287 + 5
new CP10). Ruff `check` + `format --check` clean on
`packages/llm_tracker_sdk` and `packages/llm_tracker_server`;
pre-existing lint/format drift in adjacent packages left
untouched per CLAUDE.md §2.3 surgical-changes.

Seven CP10-specific decisions, all flagged in the worklog
§Decisions §CP10; the most load-bearing:

1. **Option A: thread `min_content_level` through the SDK
   rather than rip out the mode-keyed math.** Option B (full
   replacement) would synchronously break `packages/llm_tracker/`
   and every L/A/R test under it; preserving the legacy table as
   a fallback is one diff, leaves all local-sidecar callers
   untouched, and lets the server-side host treat the
   mode/opt-in pair as inert filler. Long-term cleanup is gated
   on eventual deletion of `packages/llm_tracker/`.
2. **Default `min_content_level` is `L3`.** Matches the planning
   §Decisions ("backwards-compatible with every plugin written
   against the local-sidecar SDK"). Authors opt *down*
   explicitly; an absent field never silently restricts data the
   plugin already had access to.
3. **Per-plugin clamp is mutation on the shared `ctx`.**
   ADR-0012 pins same-instance ctx across hooks; the existing
   `ctx.egress = plugin.egress` pattern was the precedent. The
   new `_bind_plugin_view(ctx, plugin)` helper consolidates both
   per-plugin mutations into one two-line preamble shared across
   the six per-exchange dispatchers.
4. **Plugins bypassing `load_plugins` default to `L3`.** Unit
   tests that set `host._plugins = [_FooPlugin()]` directly skip
   manifest discovery; the dict-lookup default keeps the
   pre-CP10 permissive shape, which existing dispatcher tests
   rely on.
5. **TOML strings, runtime enum.** Field validator handles
   `"L1"`, `1`, and `ContentLevel.L1`; the string form is the
   documented public surface, ints + enum are conveniences for
   tests and programmatic callers.
6. **`/admin/plugins` serialises as enum name (`"L3"`, not `3`).**
   Symmetric with `allowed_modes` serialising as `["L", "A",
   "R"]`. Consumers are humans reading JSON.
7. **CP9 wiring untouched.** Storage helpers, audit context,
   the two-session forwarder split — all unchanged. CP10 did
   not change INSERT or audit shapes.

Source HEAD is now `6c3b7b8`. Documentation HEAD advances with
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

**Phase 3c CP11 — `.env.example` + developer docs refresh.**
Eleventh commit of the 14-checkpoint plan at
`docs/worklog/2026-05-11-phase3c-plan.md`:

- Rewrite `.env.example` for the server's actual surface —
  `DATABASE_URL`, log level, the (transient) Anthropic header
  convention, optional per-org token for local development.
  Remove `LLMTRACK_MODE`, `LLMTRACK_USER_OPTED_IN`, SQLite
  paths.
- Add a "running locally" section to `docs/plugins.md`
  covering the server-side load path (entry-point group,
  manifest discovery, the new CP10 `min_content_level` field
  surface).
- No Dockerfile yet — that's CP12.

Phase-3a dependencies: none for CP11. CP12 (Dockerfile) and
CP13 (Fly + secrets + staging) follow; CP14 (operator-only
end-to-end smoke) is the final checkpoint and has the soft
Phase-3a #2 dependency for *external* testing, but the
operator-only smoke is not blocked.

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
- [ ] **Phase 3a — remaining 3 decision ADRs** (#1 fallback / #2 consent / #4 agent language)
- [ ] Phase 3b — thin local agent (gated on #1 + #4)
- [ ] Phase 3c — server build-out (10 of 14 checkpoints done; remaining CP11–CP14 per `docs/worklog/2026-05-11-phase3c-plan.md`, anchored on ADR-0017/0018/0019/0020/0022)
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
