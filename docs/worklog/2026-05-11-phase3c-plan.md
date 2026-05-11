# 2026-05-11 · Phase 3c build plan

**Author**: Claude Code
**Session trigger**: User instruction — "Phase 3c kick-off — write a
build plan only, no code". One additional architecture decision was
made this session: Fly.io + Supabase as the deployment platform
(captured in ADR-0022).
**Related docs**: ADR-0017 (central-server pivot), ADR-0018 (per-org
RLS), ADR-0019 (mode taxonomy retired; L0–L3 kept as plugin
capability), ADR-0020 (per-org token + Anthropic pass-through),
ADR-0022 (Fly.io + Supabase), `docs/roadmap.md §Phase 3c`,
`docs/STATUS.md`.

## Interpretation

This is a planning-only session. Two outputs:

1. ADR-0022 documenting the deployment platform decision (Fly.io +
   Supabase). Committed first (commit `3211672`).
2. This document — a commit-by-commit plan for Phase 3c, anchored on
   ADR-0018/0019/0020/0022. **No source code is written in this
   session.** Implementation starts in the next session.

The plan must:

- Break Phase 3c into commit-sized checkpoints ordered by dependency.
- Each checkpoint: one-line description, files touched, verification
  step.
- For each checkpoint, flag any dependency on a not-yet-decided
  Phase-3a item (#1 fallback, #2 consent, #4 agent language). The
  user's expectation is that none of them should block; where they
  do, the dependency must be explicit, not silent.
- Cover at minimum: DB schema migration, auth middleware, Anthropic
  credential pass-through, storage-layer update, containerisation,
  smoke test.

## What was done

- Wrote `docs/decisions/0022-deployment-platform-fly-supabase.md` —
  ADR-0022, Accepted, Fly.io + Supabase (commit `3211672`).
- Wrote this document — the Phase 3c plan (commit `ec51a40`).
- Refreshed `docs/STATUS.md` to point at this worklog and set
  "Next single step" to CP1 (commit pending — the §5.3 atomic-three
  finalization commit).

## Phase 3c plan

Each checkpoint below is sized to be a single commit. Dependencies
flow strictly forward (CP*N* depends only on CP*<N*). The plan
assumes a greenfield server-side database: no SQLite-to-Postgres data
migration is required because the local-sidecar deployment has no
production users; the existing `supabase_sink` `public.exchanges`
rows (CP9 of the supabase-sink workstream) are operator demo data and
will be dropped/recreated under the new schema rather than migrated
in place.

A note on Phase-3a dependencies up front, because the answer is
mostly the same per checkpoint:

- **#1 (fallback when server unreachable)** is an *agent-side*
  behaviour, decided in Phase 3a / Phase 3b. The server build does
  not change shape based on it. No checkpoint below depends on it.
- **#2 (consent + data handling)** governs two things: the
  user-facing consent surface, and the storage shape (raw text vs
  scrubbed text vs metadata only). ADR-0019 §Decision item 3 says
  "Server-side storage is a single uniform shape, per ADR-0018. ...
  what that shape is (raw vs scrubbed) is settled in ADR-#2".
  CP9 (storage layer org-aware INSERTs) and CP14 (end-to-end smoke
  against real traffic) therefore have a **soft** dependency on #2:
  they can proceed using the existing Phase-1b raw-text storage
  shape (matches `supabase_sink`'s current behaviour), but the
  *default* will need revisiting once #2 lands, and the smoke test
  is operator-only until #2 sets the public consent surface.
- **#4 (agent language/distribution)** is a Phase 3b concern; the
  server is agnostic. No checkpoint below depends on it.

So only CP9 and CP14 carry a Phase-3a flag, and it is a soft
"revisit when #2 lands", not a hard block.

---

### CP1 — Bootstrap `llm_tracker_server` package

- **Change**: Empty FastAPI app with `GET /healthz`, structlog
  logging, pydantic-settings reading `LLMTRACK_*` env vars. No DB,
  no plugins, no proxy logic.
- **Files**:
  - `packages/llm_tracker_server/pyproject.toml` (add `fastapi`,
    `uvicorn[standard]`, `pydantic-settings`, `structlog`,
    `python-dotenv`; drop the stale `pynacl` line flagged by the
    signing-removal worklog).
  - `packages/llm_tracker_server/src/llm_tracker_server/__init__.py`
    (package marker, version string).
  - `.../llm_tracker_server/app.py` (FastAPI factory, healthz route,
    lifespan stub).
  - `.../llm_tracker_server/config.py` (pydantic-settings).
  - `.../llm_tracker_server/logging.py` (structlog config).
- **Verify**: `pip install -e packages/llm_tracker_server[dev]`
  succeeds; `uvicorn llm_tracker_server.app:app --port 8788` boots;
  `curl localhost:8788/healthz` returns 200. Smoke unit test
  `tests/test_healthz.py` passes.
- **Phase-3a dependencies**: none.

### CP2 — Switch DB layer to PostgreSQL (asyncpg + SQLAlchemy)

- **Change**: SQLAlchemy async engine + asyncpg driver wired in
  through `DATABASE_URL`. Alembic env moved to the server package.
  Port the three existing SQLite migrations
  (`350b17be77ae_initial_schema`, `b1c2d3e4f5a6_add_timing_columns`,
  `c2d3e4f5a6b7_audit_log_append_only_triggers`) to PostgreSQL
  dialect (BIGINT identity columns, `gen_random_uuid()` defaults,
  `CHECK` constraints in place of SQLite triggers where idiomatic;
  keep `audit_log` append-only as a Postgres trigger).
- **Files**:
  - `packages/llm_tracker_server/pyproject.toml` (add `sqlalchemy`,
    `asyncpg`, `alembic`).
  - `packages/llm_tracker_server/alembic.ini`.
  - `packages/llm_tracker_server/alembic/env.py`.
  - `packages/llm_tracker_server/alembic/versions/0001_initial_schema.py`
    (orgs/api_tokens omitted — they land in CP3).
  - `packages/llm_tracker_server/alembic/versions/0002_audit_log_triggers.py`.
  - `packages/llm_tracker_server/src/llm_tracker_server/storage/__init__.py`.
  - `.../storage/engine.py` (SQLAlchemy async engine factory).
  - `.../storage/models.py` (port `exchanges` / `events` /
    `tool_calls` / `audit_log` model definitions, Postgres types).
- **Verify**: `alembic upgrade head` succeeds against a local
  PostgreSQL 15+ container; `\d exchanges` shows expected columns;
  `pytest packages/llm_tracker_server/tests/test_storage_smoke.py`
  inserts and reads a row using the engine.
- **Phase-3a dependencies**: none.

### CP3 — `orgs` + `api_tokens` schema (ADR-0018 substrate)

- **Change**: Add tenancy substrate tables.
  - `orgs(id UUID PK default gen_random_uuid(), name text not null,
    created_at timestamptz default now())`.
  - `api_tokens(token_hash text PK, org_id UUID not null REFERENCES
    orgs(id) ON DELETE CASCADE, name text, created_at timestamptz
    default now(), revoked_at timestamptz)`. Token is stored hashed
    (SHA-256 hex); plaintext shown once at issuance.
- **Files**:
  - `packages/llm_tracker_server/alembic/versions/0003_orgs_and_tokens.py`.
  - `packages/llm_tracker_server/src/llm_tracker_server/storage/models.py`
    (add `Org`, `ApiToken`).
- **Verify**: Migration applies cleanly; an insert against `orgs`
  + `api_tokens` round-trips. Add `tests/test_org_token_models.py`
  pinning the FK + uniqueness constraints.
- **Phase-3a dependencies**: none.

### CP4 — `org_id NOT NULL` on user-data tables (ADR-0018 tenancy)

- **Change**: Add `org_id UUID NOT NULL REFERENCES orgs(id)` to
  `exchanges`, `events`, `tool_calls`, `audit_log`. No backfill is
  required (greenfield server-side schema; CP9 of supabase-sink is
  operator demo data and gets dropped/recreated).
- **Files**:
  - `packages/llm_tracker_server/alembic/versions/0004_org_id_on_user_data.py`.
  - `packages/llm_tracker_server/src/llm_tracker_server/storage/models.py`
    (add `org_id` to the four models).
- **Verify**: Migration applies; `INSERT` without `org_id` is rejected
  by the NOT NULL constraint; `INSERT` referencing an unknown
  `org_id` is rejected by the FK. Pin both rejections in
  `tests/test_org_id_constraint.py`.
- **Phase-3a dependencies**: none.

### CP5 — RLS policies + two-org isolation test (ADR-0018 enforcement)

- **Change**: Enable `ROW LEVEL SECURITY` on `exchanges`, `events`,
  `tool_calls`, `audit_log`. Policies derive the current org from
  `current_setting('app.org_id', true)::uuid`. Operator/admin role
  gets cross-org `SELECT` via an explicit policy branch (no
  service-role bypass per ADR-0018 §Decision item 2). Document the
  one-line `SET LOCAL app.org_id = '<uuid>'` invocation that CP6
  will add to every request's transaction.
- **Files**:
  - `packages/llm_tracker_server/alembic/versions/0005_rls_policies.py`.
  - `docs/decisions/0018-multi-tenancy-per-org-rls.md` (no change;
    cited only).
  - `packages/llm_tracker_server/tests/test_rls_two_org_isolation.py`
    — create org A, insert two exchanges as org A, switch session
    `app.org_id` to org B, assert `SELECT` returns zero rows; switch
    back to org A and assert two rows.
- **Verify**: `pytest` for the isolation test passes; manual
  `psql` check: as `app.org_id = <B>`, `SELECT count(*) FROM
  exchanges WHERE id IN (<A's row ids>)` returns 0.
- **Phase-3a dependencies**: none.

### CP6 — Auth middleware (ADR-0020 Axis 1)

- **Change**: FastAPI middleware extracts `Authorization: Bearer
  <token>`, hashes it, looks up `api_tokens`, sets
  `request.state.org_id` and issues `SET LOCAL app.org_id = ...` on
  the per-request DB transaction. 401 on missing/malformed
  Authorization, 403 on unknown/revoked token. CLI subcommand
  `llm-tracker-server tokens issue --org <name>` mints a new token
  (prints plaintext once, stores hash). Token-issuance scrubbed
  from server log lines via the structlog processor.
- **Files**:
  - `.../llm_tracker_server/auth/__init__.py`.
  - `.../auth/middleware.py` (the FastAPI middleware).
  - `.../auth/tokens.py` (hash, lookup, issue).
  - `.../cli/__init__.py`, `.../cli/main.py` (Typer entry point —
    `tokens issue`, `tokens revoke`, `tokens list`).
  - `packages/llm_tracker_server/pyproject.toml` (add `typer`,
    declare `llm-tracker-server` console script).
  - `tests/test_auth_middleware.py` — three cases: missing
    Authorization → 401; unknown token → 403; valid token →
    `request.state.org_id` set, downstream handler sees correct
    `app.org_id`.
- **Verify**: Test file passes; `llm-tracker-server tokens issue
  --org demo` prints a token; `curl -H "Authorization: Bearer <tok>"
  /admin/whoami` returns the org id.
- **Phase-3a dependencies**: none. (#3 was settled by ADR-0020.)

### CP7 — Anthropic credential pass-through + log scrubbing (ADR-0020 Axis 2)

- **Change**: Forward whichever Anthropic-credential header Claude
  Code natively sends (`x-api-key`; confirm during this checkpoint
  per ADR-0020 §Open questions) on the outbound httpx call to
  `api.anthropic.com`. **Never** persist it: no DB column, no log
  line, no audit detail. structlog processor strips the credential
  header from every log entry; an explicit unit test asserts the
  header bytes never appear in a captured log buffer.
- **Files**:
  - `.../llm_tracker_server/proxy/__init__.py`.
  - `.../proxy/forwarder.py` (httpx async client + SSE relay; port
    the relevant bits from `packages/llm_tracker/src/llm_tracker/proxy/`).
  - `.../proxy/credential.py` (extract on inbound, attach to
    outbound, scrub from logs).
  - `.../logging.py` (add the credential-scrubbing structlog
    processor).
  - `tests/test_credential_passthrough.py` (assert outbound request
    carries the header; assert no log line ever contains it).
- **Verify**: Test file passes; manual local test against a stub
  upstream confirms the header round-trips and `journalctl`/stdout
  shows no leakage.
- **Phase-3a dependencies**: none. (#3 was settled by ADR-0020.)

### CP8 — Port proxy + plugin host server-side (ADR-0017 / ADR-0019)

- **Change**: Move FastAPI catch-all route, SSE Tee, hook lifecycle,
  `PluginHost`, `EgressGuard`, and `HookContext` from
  `packages/llm_tracker/src/llm_tracker/` to
  `packages/llm_tracker_server/src/llm_tracker_server/`. Drop the
  Mode L/A/R enum and `LLMTRACK_MODE` resolution (ADR-0019
  §Decision item 1). Drop the `LLMTRACK_USER_OPTED_IN` env knob
  (ADR-0016 was a Mode-R interim consent surface; superseded by the
  upcoming consent ADR-#2 and by per-org tokens which are the new
  identity anchor). The local-sidecar `packages/llm_tracker/`
  package itself stays in tree as historical scaffolding until ADR-#4
  (agent language) decides Phase 3b — see Open follow-ups.
- **Files**:
  - New: `.../llm_tracker_server/proxy/app.py` (catch-all + Tee),
    `.../proxy/sse.py`, `.../plugin_host/host.py`,
    `.../plugin_host/manifest.py`, `.../plugin_host/hooks.py`,
    `.../plugin_host/context.py`, `.../egress_guard/guard.py`,
    `.../egress_guard/client.py`, `.../content_levels/levels.py`.
  - Modified: `.../llm_tracker_server/app.py` (wire all the above
    into the FastAPI factory).
  - `tests/` mirror — port the Phase 0–1b suites that still apply
    (capability registry, hook dispatcher ordering, content-level
    routing, EgressGuard wiring). Skip the Mode-keyed policy tests
    retired by ADR-0019.
- **Verify**: `pytest packages/llm_tracker_server/tests` passes,
  including ported hook-lifecycle and EgressGuard tests; the existing
  `packages/llm_tracker/tests` suite is left untouched in this
  checkpoint (it is still the historical reference until the
  package itself is retired).
- **Phase-3a dependencies**: none. (ADR-0019 already retired the
  pieces tied to the deferred items.)

### CP9 — Storage layer: org-aware INSERTs (ADR-0018 + ADR-0020 wiring)

- **Change**: Every INSERT path in the ported storage layer
  (`exchanges`, `events`, `tool_calls`, `audit_log`) writes
  `org_id = request.state.org_id`. The DB session opened per
  request also issues `SET LOCAL app.org_id = ...` (CP5's RLS
  context). Defense in depth: the column is set explicitly even
  though RLS would block a wrong-org write. Add a two-org
  end-to-end isolation test through the real `/v1/messages` path:
  issue a request as org A, assert the exchange row in org B's
  session-scope is invisible.
- **Files**:
  - Modified: `.../llm_tracker_server/storage/exchanges.py`,
    `.../storage/events.py`, `.../storage/tool_calls.py`,
    `.../storage/audit_log.py` (whichever names CP8 chose — the
    point is the org-id wiring, not the names).
  - Modified: `.../llm_tracker_server/proxy/forwarder.py` (open the
    DB session inside the request scope; `SET LOCAL` before any
    write).
  - `tests/test_two_org_e2e_isolation.py`.
- **Verify**: New test passes; manual `psql`: as org B, `SELECT *
  FROM exchanges` after an org-A request returns 0 rows.
- **Phase-3a dependencies**: **soft dependency on #2 (consent +
  data handling)**. The storage shape used here is raw text
  (matches the current `supabase_sink` and Phase-1b SQLite shape).
  ADR-0019 explicitly delegates "raw vs scrubbed" to ADR-#2; this
  checkpoint proceeds with raw because it matches the current
  baseline, but the default will need a follow-up pass once #2
  lands. Flagged in this worklog and in the commit message.

### CP10 — `min_content_level` manifest field + host enforcement (ADR-0019 §Open questions)

- **Change**: Add `min_content_level` to the plugin manifest schema
  (default `L3`; valid values `L0` / `L1` / `L2` / `L3`). The
  server-side `PluginHost` clamps each plugin's `HookContext` view
  to the declared level — a plugin asking for `L0` cannot reach
  `request_text` even if the data is in memory. Pin the existing
  `test_hook_context.py::test_request_text_returns_body_at_l2_when_ceiling_allows`
  semantics carry over to the server package. Drop the
  Mode-keyed intersection logic (ADR-0019 §Consequences).
- **Files**:
  - Modified: `.../llm_tracker_server/plugin_host/manifest.py`
    (validator).
  - Modified: `.../plugin_host/context.py` (clamping).
  - Modified: `packages/llm_tracker_sdk/` if the SDK exports the
    manifest schema or a `min_content_level` enum (light touch —
    a single new field).
  - `tests/test_min_content_level.py` — declare a plugin at L1,
    assert it cannot access `request_text`; declare another at L3,
    assert it can.
- **Verify**: Test file passes; introspection endpoint
  `/admin/plugins` (ADR-0014) reports each plugin's declared level.
- **Phase-3a dependencies**: none.
  *Scrubber primitives (L2 with proper meaning) are still owed —
  inherited from Phase 1c; tracked as a follow-up, not a blocker
  for this checkpoint, because L2 will fall back to L3-bytes until
  scrubbers land (already the current behaviour, pinned by the
  existing test).*

### CP11 — `.env.example` + developer docs refresh

- **Change**: Rewrite `.env.example` for the server's actual
  surface — `DATABASE_URL`, log level, optional per-org token for
  local development, the (transient) Anthropic header convention.
  Remove `LLMTRACK_MODE`, `LLMTRACK_USER_OPTED_IN`, SQLite paths.
  Add a "running locally" section to `docs/plugins.md` covering
  the server-side load path. No Dockerfile yet — this is the
  documentation pass before containerisation.
- **Files**:
  - `.env.example` (rewrite).
  - `docs/plugins.md` (server-side load-path section — small).
  - `docs/STATUS.md` (will be touched at end-of-session anyway;
    leave for the §5.3 checkpoint, not here).
- **Verify**: A fresh checkout + `.env` from `.env.example` +
  `uvicorn llm_tracker_server.app:app` boots cleanly; no remaining
  references to retired knobs in `.env.example` (grep).
- **Phase-3a dependencies**: none.

### CP12 — `Dockerfile` (ADR-0022)

- **Change**: Multi-stage Dockerfile at the repo root. Base
  `python:3.11-slim`; build stage installs `packages/llm_tracker_server`
  + its deps; runtime stage copies the venv and runs `uvicorn
  llm_tracker_server.app:app --host 0.0.0.0 --port 8080`. Healthcheck
  hits `/healthz`. `.dockerignore` to keep the image small.
- **Files**:
  - `Dockerfile` (new).
  - `.dockerignore` (new).
- **Verify**: `docker build -t llm-tracker-server .` succeeds;
  `docker run -e DATABASE_URL=... -p 8080:8080 llm-tracker-server`
  boots; `curl localhost:8080/healthz` returns 200; final image is
  under ~300 MB.
- **Phase-3a dependencies**: none.

### CP13 — `fly.toml` + secrets + staging deploy (ADR-0022)

- **Change**: `fly.toml` at the repo root declaring the http
  service, internal port 8080, /healthz health check, single
  region (`iad`). `fly secrets set DATABASE_URL=...` (Supabase
  pooled connection string). Decide migration runner (Fly release
  command vs CI step — recommend release command for the demo
  scale) and wire it in. Provision a demo org + token via the CLI.
- **Files**:
  - `fly.toml` (new).
  - `docs/STATUS.md` mention via the §5.3 checkpoint, not in this
    file.
- **Verify**: `fly deploy` succeeds; `fly status` shows the app
  healthy; `curl https://<app>.fly.dev/healthz` returns 200;
  `flyctl ssh console -C 'llm-tracker-server tokens issue --org
  demo'` returns a token.
- **Phase-3a dependencies**: none.

### CP14 — End-to-end smoke

- **Change**: Real Claude Code session, no code change. Set
  `ANTHROPIC_BASE_URL=https://<app>.fly.dev` and `ANTHROPIC_API_KEY=...`
  on the operator's machine; per-org token attached however Phase
  3b will eventually attach it (for this checkpoint: a manually
  set `Authorization: Bearer` via a thin shell wrapper, since Phase
  3b is still pending). Drive one request through Claude Code.
- **Files**: none (this is verification, not a code change). The
  resulting transcript becomes part of the worklog narrative.
- **Verify**: Claude Code completes the request normally; the Fly
  log stream shows the request lifecycle; `SELECT count(*),
  org_id FROM exchanges GROUP BY org_id` in Supabase shows exactly
  one row with the demo org's id; `request_text` populated;
  `grep -i 'x-api-key\|sk-ant'` on the captured Fly log stream
  returns nothing.
- **Phase-3a dependencies**: **soft dependency on #2 (consent +
  data handling)**. The smoke test runs against the operator's own
  Anthropic account and operator's own data, so the consent surface
  isn't yet exercised. STATUS.md §"Blocking / decisions needed"
  already records that #2 is required before *any external
  testing* — CP14 is operator-only and that's the limit. External
  smoke is gated on #2 landing.

---

## Decisions

- **Used the descriptive ADR filename
  `0022-deployment-platform-fly-supabase.md`** instead of the user's
  literal `0022-deploymentm.md` (clearly a typo — duplicated "m";
  no other ADR uses the truncated form). Style matches
  ADR-0017/0018/0019/0020/0021. Flagged here so the typo isn't
  silently corrected later.
- **Greenfield server-side database, no SQLite→Postgres data
  migration.** The local-sidecar deployment has no production
  users (the only populated database is the operator's local
  `.var/llm_tracker.db` plus the operator's `supabase_sink` demo
  data); migrating either would be wasted effort. CP9 of the
  supabase-sink workstream is operator demo data and will be
  re-created against the new schema. Documented in CP4.
- **`LLMTRACK_USER_OPTED_IN` is retired in CP8.** ADR-0016 was an
  interim Mode-R consent surface; ADR-0019 retired Mode-R, and
  per-org tokens (ADR-0020) are the new identity anchor. The
  upcoming ADR-#2 will set the new consent surface explicitly; the
  env knob is not preserved as a placeholder because doing so
  would silently encode a guess about #2's outcome.
- **`min_content_level` defaults to `L3`.** Backwards-compatible
  with every plugin written against the local-sidecar SDK (none of
  them declared a level; they all received raw bytes). CP10 enforces
  the field; opting *down* is the plugin author's choice.
- **`packages/llm_tracker/` is not deleted as part of Phase 3c.**
  ADR-0017 §Reversibility explicitly preserved it as reusable
  scaffolding; ADR-#4 (agent language) may pull the catch-all + base
  URL bits back into the thin agent. Deletion is a Phase 3b/3c-end
  housekeeping decision, not this checkpoint sequence.
- **No service-role bypass in operator tooling.** Per ADR-0018
  §Decision item 2: admin queries get an `admin` policy branch
  inside RLS, not a side door. CP6's `/admin/...` routes (when they
  appear) will run under a session that asserts `app.role = 'admin'`
  alongside `app.org_id`.

## Verification

This is a documentation-only session.

- ADR-0022 written and committed (`3211672`).
- This plan document written and committed (commit pending).
- No source-tree changes. `pytest` and `ruff` not run; nothing to
  verify them against. The plan itself is verified at the next
  session's CP1 — if CP1 is achievable from the plan as written,
  the plan is sound.

Internal-link sanity:

- All four anchor ADRs (`0017`, `0018`, `0019`, `0020`) exist in
  `docs/decisions/`. ADR-0022 was created above and is committed.
- `docs/STATUS.md`, `docs/roadmap.md`, the signing-removal worklog,
  and the supabase-sink CP4 worklog all exist where this document
  references them.

## What's left / known limits

- **The plan is 14 checkpoints; it is not the implementation.** Next
  session executes CP1.
- **Soft Phase-3a dependencies on #2 (consent + data handling)** at
  CP9 and CP14 only. Both flagged inline. Neither blocks the build
  from starting; both gate external exposure.
- **Open ADR-0022 questions** (migration runner location, secrets
  management specifics, region selection) resolve naturally inside
  CP13. None are blockers for earlier checkpoints.
- **Scrubber primitives** (Phase 1c remnant, called out by ADR-0019
  §Open questions and `docs/STATUS.md §Phase 1c prerequisites`)
  are not on the CP list. They surface only when ADR-#2 commits to
  L2-as-scrubbed-text as the default storage shape. Until then,
  L2-declaring plugins receive L3 bytes — current behaviour,
  test-pinned, harmless.
- **Response-side `ctx` accessors** (`response_text`,
  `tool_call_inputs`, etc.) inherited from ADR-0012 §Open
  questions: not on the CP list. Lands when the Phase-2 extractor
  surfaces structured response records; separate ADR if semantics
  surface anything non-obvious.

## Handoff

`HEAD` after this worklog's §5.3 commit will be at the STATUS-update
commit referenced below. Next session's entry is the standard
"resume" prompt against `docs/STATUS.md` — that file's
"Next single step" is now **CP1: Bootstrap `llm_tracker_server`
package** as scoped above.

The plan is the contract. Each checkpoint is one commit. Don't
batch checkpoints into a single commit; each one has its own
verification surface and ought to be greppable in `git log` later.

## Suggestions (untouched)

1. **Phase 3b kick-off planning** should follow the same plan-first
   pattern once #1 (fallback) and #4 (agent language) land. The
   thin-agent surface is small but has its own dependency chain
   (language choice → distribution → bootstrapping handshake →
   secret storage).
2. **`docs/design.md` rewrite** — the document still describes the
   local-sidecar architecture in detail. Recommended pass at the
   tail end of Phase 3c (after CP14) so the rewrite reflects the
   built thing rather than the planned thing.
3. **`docs/roadmap.md §Phase 1c`** can be retired or rewritten
   in-place once CP8 lands — the embedding/LLM judge is no longer
   a per-user machine concern. Either fold into a "Phase 3d —
   scope_guard server-side" entry or strike entirely.
4. **`packages/llm_tracker_server/pyproject.toml` `pynacl` line**
   gets removed in CP1's deps refresh (also resolves Suggestion #1
   of the signing-removal worklog).
