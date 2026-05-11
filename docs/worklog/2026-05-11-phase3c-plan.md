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

### Planning session (2026-05-11)

- Wrote `docs/decisions/0022-deployment-platform-fly-supabase.md` —
  ADR-0022, Accepted, Fly.io + Supabase (commit `3211672`).
- Wrote this document — the Phase 3c plan (commit `ec51a40`).
- Refreshed `docs/STATUS.md` to point at this worklog and set
  "Next single step" to CP1 (commit `f866cb8`).

### CP3 — `orgs` + `api_tokens` schema (2026-05-11, commit `373ed11`)

- New migration
  `packages/llm_tracker_server/alembic/versions/0003_orgs_and_tokens.py`:
  - `orgs(id UUID PK DEFAULT gen_random_uuid(), name text NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL)`. PG 13+ ships
    `gen_random_uuid()` in core, so no extension load is required.
  - `api_tokens(token_hash text PK, org_id UUID NOT NULL REFERENCES
    orgs(id) ON DELETE CASCADE, name text NULL, created_at timestamptz
    DEFAULT now() NOT NULL, revoked_at timestamptz NULL)`. The
    plaintext token is stored only as its SHA-256 hex (ADR-0020 §"Token
    issuance"); the `revoked_at` nullable column carries the
    revocation surface that CP6's `tokens revoke` CLI will write.
- `packages/llm_tracker_server/src/llm_tracker_server/storage/models.py`
  gained two new ORM classes:
  - `Org` — `id: Mapped[uuid.UUID]` on
    `postgresql.UUID(as_uuid=True)` with
    `server_default=text("gen_random_uuid()")`. `created_at` uses
    `postgresql.TIMESTAMP(timezone=True)` with `server_default=text("now()")`.
  - `ApiToken` — `token_hash` PK, `org_id` typed as PG UUID with
    `ForeignKey("orgs.id", ondelete="CASCADE")`.
  - Module docstring extended to call out that CP3 is the first
    place identity generation lives at the DB layer (no app-layer
    contract to break, unlike the ULID-keyed four user-data tables).
- `packages/llm_tracker_server/src/llm_tracker_server/storage/__init__.py`
  re-exports `ApiToken` and `Org` alongside the existing surface and
  documents the CP3 ⇆ CP4 split.
- New `packages/llm_tracker_server/tests/test_org_token_models.py`
  with four assertions (all skipif-without-`LLMTRACK_TEST_DATABASE_URL`):
  - `test_org_server_side_uuid_default` — insert without `id`, the
    DB fills it; `created_at.tzinfo` is non-None (tz-aware).
  - `test_api_token_fk_rejects_unknown_org` — inserting a token
    against `uuid.uuid4()` raises `sa.exc.IntegrityError`.
  - `test_api_token_hash_is_unique` — duplicate PK insert raises
    `sa.exc.IntegrityError`.
  - `test_api_token_cascade_on_org_delete` — after `DELETE FROM
    orgs`, the two token rows are gone.
  Fixture shape is a copy of `test_storage_smoke.py`'s — see
  Decisions §CP3 for why I didn't factor a shared `conftest.py`.

### CP2 — switch DB layer to PostgreSQL (2026-05-11, commit `b7eed52`)

- Added `sqlalchemy>=2`, `asyncpg`, `alembic` to
  `packages/llm_tracker_server/pyproject.toml` runtime deps. `uv sync`
  added `asyncpg==0.31.0`; `sqlalchemy` and `alembic` were already in
  the lockfile via `packages/llm_tracker`.
- Extended `Settings` with `database_url: str = ""`
  (`LLMTRACK_DATABASE_URL`). Empty default keeps `/healthz` booting
  without a DB; the storage entry points raise `ValueError` if asked
  for an engine without a URL.
- Created `packages/llm_tracker_server/src/llm_tracker_server/storage/`:
  - `engine.py` — `make_engine(url) -> AsyncEngine` +
    `make_session_factory(engine)`.
  - `models.py` — `Base` + four ORM models (`Exchange`, `Event`,
    `ToolCall`, `AuditLog`) ported one-to-one from
    `llm_tracker.storage.models` with `BigInteger` substituted for
    `Integer` on every epoch-ms / counter column (PG `INT4` would
    overflow epoch-ms in 2038). String/ULID PKs preserved — see
    Decisions §CP2 for why the plan's "BIGINT identity / UUID
    default" wording was taken as guidance for CP3 tables only.
  - `__init__.py` — flat re-export so callers can
    `from llm_tracker_server.storage import Exchange, make_engine,
    make_session_factory`.
- Created Alembic env at `packages/llm_tracker_server/alembic/`:
  - `alembic.ini` — `script_location = %(here)s/alembic`, fallback
    `sqlalchemy.url` for offline mode only; the env reads
    `LLMTRACK_DATABASE_URL` at runtime and overrides.
  - `env.py` — async-engine online mode (asyncpg) + offline mode;
    imports `llm_tracker_server.storage.models.Base` as
    `target_metadata`. Mirrors the local-sidecar `llm_tracker/alembic/env.py`.
  - `script.py.mako` — single-DB template.
  - `versions/0001_initial_schema.py` — consolidates SQLite-era
    `350b17be77ae_initial_schema` + `b1c2d3e4f5a6_add_timing_columns`
    (greenfield server, nothing to migrate forward). All epoch-ms /
    counter columns are `sa.BigInteger()`; `tool_call_count` has
    `server_default="0"`.
  - `versions/0002_audit_log_triggers.py` — replaces the SQLite
    `RAISE(ABORT)` per-table triggers with a single PL/pgSQL function
    `audit_log_reject_modify()` bound to two `BEFORE ... FOR EACH
    ROW` triggers (UPDATE + DELETE). Mirrors ADR-0006 §audit_log.
- Created `packages/llm_tracker_server/tests/test_storage_smoke.py`:
  - `pytest.fixture session_factory` runs `alembic upgrade head` /
    `downgrade base` around each test via a subprocess invocation
    of `python -m alembic` inside the server package dir, with
    `LLMTRACK_DATABASE_URL` forwarded.
  - `test_exchange_round_trip` inserts an `Exchange`, reads it back,
    asserts every populated field.
  - `test_audit_log_append_only` confirms the PG trigger rejects
    `UPDATE` and `DELETE` against `audit_log` with the
    "append-only" message.
  - Both tests skip when `LLMTRACK_TEST_DATABASE_URL` is unset, so
    the wider suite stays green on machines without a local PG.

### CP1 — bootstrap `llm_tracker_server` package (2026-05-11, commit `7d992ff`)

- Rewrote `packages/llm_tracker_server/pyproject.toml`: dropped the
  stale `pynacl` dep (signing-removal Suggestion #1, now resolved);
  added `fastapi`, `uvicorn[standard]`, `pydantic-settings`,
  `structlog`, `python-dotenv` as runtime deps; `pytest`,
  `pytest-asyncio`, `httpx`, `ruff`, `mypy` as dev deps. Description
  field refreshed to reflect the post-ADR-0017 central-server role
  rather than the retired "Mode R receiver" framing.
- Created `packages/llm_tracker_server/src/llm_tracker_server/app.py`:
  `create_app(settings: Settings | None = None) -> FastAPI` factory
  plus a module-level `app = create_app()` so
  `uvicorn llm_tracker_server.app:app` works. CP1 surface is
  `GET /healthz` only — DB, auth, proxy routes, and plugin host
  land in CP2/CP3+/CP6/CP7/CP8. `docs_url=None`/`redoc_url=None`
  mirrors the existing `llm_tracker` proxy app (no auth on auto-docs).
- Created `packages/llm_tracker_server/src/llm_tracker_server/config.py`:
  `Settings(BaseSettings)` with `env_prefix="LLMTRACK_"`, single
  `log_level: str = "INFO"` field for CP1. Future checkpoints
  (`DATABASE_URL` in CP2, etc.) extend it.
- Created `packages/llm_tracker_server/src/llm_tracker_server/logging.py`:
  `configure_logging(level)` wiring structlog's JSON renderer +
  contextvars + iso timestamps. Inline note that CP7 will append
  the Anthropic-credential scrubber per ADR-0020.
- Refreshed `packages/llm_tracker_server/src/llm_tracker_server/__init__.py`
  docstring to point at ADR-0017 + the Phase 3c plan; bumped/kept
  `__version__ = "0.0.1"`.
- Created `packages/llm_tracker_server/tests/test_healthz.py`:
  `httpx.AsyncClient` + `ASGITransport` smoke test asserting
  `GET /healthz` returns `{"status": "ok", "version": __version__}`
  with status 200. (No `tests/__init__.py` — matches the rootdir-mode
  layout used by the plugin packages; see Decisions below.)
- Modified root `pyproject.toml`: added
  `packages/llm_tracker_server/tests` to `[tool.pytest.ini_options]
  testpaths` so the full-suite invocation collects the server tests.
- `uv.lock` regenerated by `uv sync` — uninstalled the now-unused
  `pynacl`, `keyring`, `cffi`, `pycparser`, `jaraco-*`, `more-itertools`
  chain that was carried only by `pynacl`.

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

### Planning session

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

### CP3

- **Dialect-specific `postgresql.UUID(as_uuid=True)` +
  `postgresql.TIMESTAMP(timezone=True)` on the models**, not SA-2's
  portable `Uuid` / `DateTime(timezone=True)`. The plan called out
  "`sqlalchemy.dialects.postgresql.UUID` (or SA-2 `Uuid`)"; the
  migration is already PG-only, and matching the dialect import on both
  sides keeps alembic autogenerate diff-clean if a future checkpoint
  ever runs one against the live schema. The portable types would
  produce visible noise in those diffs (`VARCHAR(32)` vs `UUID`,
  `TIMESTAMP` vs `TIMESTAMP WITH TIME ZONE`).
- **`gen_random_uuid()` instead of `uuid_generate_v4()`.** PG 13+
  ships `gen_random_uuid()` in core; `uuid_generate_v4()` requires
  loading the `uuid-ossp` extension. ADR-0022 pins PG 15+ via
  Supabase, so we get the core function for free and avoid a
  migration-time `CREATE EXTENSION`. Documented in the migration
  header so a future reader on a pre-PG-13 fork knows where the
  assumption lives.
- **No index on `api_tokens.org_id`.** PG does not auto-index FK
  columns. The hot lookup path in CP6 is by `token_hash` (already the
  PK), not by `org_id`. `ON DELETE CASCADE` over a token set that's
  expected to stay in the single-digit-per-org range is fine without
  one. If CP6 or the admin tooling later wants a `WHERE org_id = $1`
  listing path, add the index in its own migration — don't pre-index
  for a query we haven't written.
- **Token hash stored as `TEXT`, not `bytea` or `CHAR(64)`.** The
  application layer hex-encodes the SHA-256 digest, so `TEXT` is the
  unambiguous shape and saves an encoding coercion in the auth
  middleware lookup. PG `TEXT` has no length-scaling penalty over
  `VARCHAR(64)`.
- **CP3's smoke-test fixture is copy-pasted from `test_storage_smoke.py`
  rather than factored into a shared `conftest.py`.** Each test file
  currently runs its own alembic upgrade/downgrade subprocess wrapper;
  hoisting the fixture would need a parameter for the per-test reset
  cadence and is over the line for "CP3 = schema + one test file".
  Resolve as a `conftest.py` cleanup pass when CP4 / CP5 fixtures
  arrive and the duplication is three-deep. Flagged in Suggestions.
- **Test exceptions narrowed to `sa.exc.IntegrityError`** rather than
  the broad `Exception` matcher used by `test_audit_log_append_only`.
  The audit-log path raises a generic PL/pgSQL error that arrives via
  asyncpg as a raw `DBAPIError`; the FK / PK violations here come
  through PG's standard error codes which SA-2 maps to
  `IntegrityError`. Narrower matcher catches a regression where the
  driver layer changes (e.g. asyncpg → psycopg). Different shape,
  different matcher — kept consistent with the failure model.

### CP2

- **String/ULID primary keys preserved on the four ported tables**,
  not switched to `BIGINT GENERATED ALWAYS AS IDENTITY` or `UUID
  DEFAULT gen_random_uuid()`. The plan's CP2 entry mentions both,
  but Phase 1 / Phase 2 code (extractors, supabase-sink parser,
  storage writers) all produce ULID strings at the application
  layer. Swapping the column type would have cascaded into those
  callers without buying anything CP2 actually needs. Read the
  plan's identity/UUID note as forward-pointing guidance for the
  CP3 tenancy tables (`orgs.id UUID`, `api_tokens.token_hash` text)
  rather than retroactive rework of the existing schema.
- **`Integer` → `BigInteger` on every epoch-ms / counter column.**
  SQLite's INTEGER is variable-width so the SQLite source compiled
  fine with `sa.Integer()`; PG `INT4` would overflow epoch-ms by
  2038. Flagged explicitly in the models module docstring so a
  future reader doesn't "simplify" it back.
- **Initial migration consolidates the two SQLite migrations.** The
  plan listed them as separate ports, but the greenfield server
  schema has nothing to migrate forward — replaying timing columns
  as a follow-up migration would just be ceremony. Consolidation
  matches the plan's `0001_initial_schema` filename anyway.
- **Audit-log triggers use one PL/pgSQL function + two
  `BEFORE ... FOR EACH ROW` triggers**, not two trigger bodies. PG
  trigger functions must return `TRIGGER` and live in a separate
  CREATE FUNCTION; this is the idiomatic shape and downgrade drops
  both triggers and the function. ADR-0006 §audit_log is the
  source of truth — the SQL form is dialect-specific.
- **The smoke test fixture invokes alembic via `subprocess` rather
  than the in-process `command.upgrade` API.** Reason: in-process
  alembic on an async engine fights the test event loop (alembic's
  online migration spins its own `asyncio.run`). The subprocess
  shape is identical to how CI / Fly release commands will run it,
  so it doubles as integration coverage.
- **`LLMTRACK_TEST_DATABASE_URL` is a *test-only* env var.** The
  app's runtime URL is `LLMTRACK_DATABASE_URL`. Keeping them
  distinct lets a developer aim the test fixture at an ephemeral
  container while the rest of the workspace points at staging /
  Supabase. The smoke test passes the test URL through into the
  alembic subprocess as `LLMTRACK_DATABASE_URL`.

### CP1

- **No `tests/__init__.py` in the server package** — matches the
  rootdir-mode layout used by `llm_tracker_plugin_token_counter`,
  `llm_tracker_plugin_keyword_block`, and
  `llm_tracker_plugin_supabase_sink`. My first attempt included one;
  pytest refused to collect (`ModuleNotFoundError: No module named
  'tests.test_healthz'`) because `llm_tracker/tests` already claims
  the top-level `tests` package namespace. Deleted the file; the
  plan's CP1 file list is amended accordingly.
- **Settings has only `log_level` for CP1.** The plan's CP1 entry
  said "pydantic-settings reading `LLMTRACK_*` env vars" but did
  not enumerate fields. Adding speculative fields now (a hypothetical
  `LLMTRACK_HOST`, `LLMTRACK_PORT`, etc.) would violate CLAUDE.md
  §2.2's "no flexibility that wasn't requested" — uvicorn already
  takes host/port on its CLI. Each future checkpoint adds the
  Settings field it actually uses.
- **Logging module named `logging.py` per the plan**, even though
  it shadows stdlib's `logging` *within the package namespace*.
  Inside `logging.py` itself I aliased the stdlib as
  `import logging as stdlib_logging` to keep intent obvious; from
  callers, the fully-qualified `llm_tracker_server.logging` is
  unambiguous.
- **structlog processor chain is minimal** — `merge_contextvars`,
  `add_log_level`, ISO `TimeStamper`, `JSONRenderer`. The
  Anthropic-credential scrubber (ADR-0020) is explicitly *not*
  added yet; CP7 owns it. The file's docstring carries that
  forward-reference so a future reader doesn't add their own.
- **Auto-load `.env` inside `create_app()`** via `python-dotenv`,
  mirroring `packages/llm_tracker/src/llm_tracker/proxy/app.py`'s
  lifespan. `override=False` so shell-exported values win — same
  convention as the existing proxy.
- **Description field on `pyproject.toml` and the package
  `__init__.py` were both rewritten.** The previous wording ("Mode
  R receiver app", "pairs with `supabase_sink`") was actively
  misleading post-ADR-0017/0019. Strictly speaking this is beyond
  "CP1 = bootstrap deps + healthz" — but a description that lies
  about what the package does is worse than a one-line edit. Flagged
  here so the plan-versus-execution drift is visible.
- **Did *not* delete the `llm_tracker_plugin_supabase_sink` package
  even though its operational role shrinks once the server stores
  exchanges directly.** That's a Phase-3d / cleanup decision once
  CP9 lands and the operator confirms the sink is no longer needed
  as a separate write path. Out of CP1's scope.

## Verification

### Planning session

- ADR-0022 written and committed (`3211672`).
- This plan document written and committed (`ec51a40`).
- Plan's internal links sanity-checked: all four anchor ADRs
  (`0017`, `0018`, `0019`, `0020`) exist in `docs/decisions/`;
  `docs/STATUS.md`, `docs/roadmap.md`, the signing-removal worklog,
  and the supabase-sink CP4 worklog all exist at the cited paths.

### CP3

Alembic offline-mode SQL gen against the new revision (proves the
DDL is well-formed and the FK + cascade are encoded as written):

```
$ cd packages/llm_tracker_server && \
    LLMTRACK_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/llm_tracker \
    .../python3.12 -m alembic upgrade \
      0002_audit_log_triggers:0003_orgs_and_tokens --sql
...
-- Running upgrade 0002_audit_log_triggers -> 0003_orgs_and_tokens

CREATE TABLE orgs (
    id UUID DEFAULT gen_random_uuid() NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE api_tokens (
    token_hash TEXT NOT NULL,
    org_id UUID NOT NULL,
    name TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (token_hash),
    FOREIGN KEY(org_id) REFERENCES orgs (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='0003_orgs_and_tokens'
  WHERE alembic_version.version_num = '0002_audit_log_triggers';
COMMIT;
```

Live verification against the ephemeral PostgreSQL 15.17 container
(reused from CP2; `docker run ...` parameters identical to CP2's):

```
$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_server/tests/test_org_token_models.py -q
....                                                                     [100%]
4 passed in 2.23s
```

Full suite with the test URL set (both CP2 smokes + the four CP3
tests run; the rest of the suite ignores the test URL):

```
$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest -q
...
255 passed, 4 warnings in 10.28s
```

Full suite without the test URL (PG smokes skip; this is the path
CI and other developers will see by default):

```
$ .venv/bin/python3.12 -m pytest -q
...
249 passed, 6 skipped, 4 warnings in 7.04s
```

The four warnings are the same pre-existing `DeprecationWarning:
fork()` from `llm_tracker/cli/manage.py`, unchanged from CP1/CP2.

Ruff:

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_server
All checks passed!
$ .venv/bin/python3.12 -m ruff format --check packages/llm_tracker_server
14 files already formatted
```

Two CP3 autofixes during the pass: ruff `format` rewrote a
multi-line `select(...).execute()` to fit-on-one-line on the org
round-trip test, and `check` flagged an `I001` import sort in
`models.py` (the `import uuid as uuid_module` was on the wrong side
of `from datetime import datetime`). Both applied without
structural change.

### CP2

`uv sync` after the pyproject edit:

```
Resolved 60 packages in 262ms
Prepared 2 packages in 266ms
Uninstalled 1 package in 5ms
Installed 2 packages in 1ms
 + asyncpg==0.31.0
 ~ llm-tracker-server==0.0.1
```

`sqlalchemy` and `alembic` were already in `uv.lock` via the
`llm_tracker` package — only `asyncpg` was newly added.

Alembic offline-mode SQL gen against a placeholder URL (proves the
env loads + the migrations produce valid PG syntax without needing
a live DB):

```
$ LLMTRACK_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/llm_tracker \
    .venv/bin/python3.12 -m alembic upgrade head --sql
INFO  [alembic.runtime.migration] Running upgrade -> 0001_initial_schema
...
CREATE TABLE exchanges (..., started_at BIGINT NOT NULL, ...);
CREATE INDEX idx_exchanges_started ON exchanges (started_at);
...
INFO  [alembic.runtime.migration] Running upgrade 0001_initial_schema -> 0002_audit_log_triggers
CREATE OR REPLACE FUNCTION audit_log_reject_modify() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
FOR EACH ROW EXECUTE FUNCTION audit_log_reject_modify();
CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
FOR EACH ROW EXECUTE FUNCTION audit_log_reject_modify();
UPDATE alembic_version SET version_num='0002_audit_log_triggers' WHERE ...;
COMMIT;
```

Live verification against an ephemeral PostgreSQL 15 container:

```
$ docker run -d --name llm-tracker-pg-cp2 \
    -e POSTGRES_USER=cp2 -e POSTGRES_PASSWORD=cp2 \
    -e POSTGRES_DB=llm_tracker_test \
    -p 55432:5432 postgres:15
$ docker exec llm-tracker-pg-cp2 psql -U cp2 -d llm_tracker_test \
    -c "SELECT version();"
PostgreSQL 15.17 (Debian 15.17-1.pgdg13+1) on aarch64-unknown-linux-gnu, ...

$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_server/tests/test_storage_smoke.py -q
..                                                                       [100%]
2 passed in 1.72s
```

Full suite with the test URL set (both PG smokes ran; rest of the
suite ignores `LLMTRACK_TEST_DATABASE_URL`):

```
$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest -q
...
251 passed, 4 warnings in 8.13s
```

Full suite without the test URL (PG smokes skip; this is the path CI
and other developers will see by default):

```
$ .venv/bin/python3.12 -m pytest -q
...
249 passed, 2 skipped, 4 warnings in 7.13s
```

The four warnings are the same pre-existing `DeprecationWarning:
fork()` from `llm_tracker/cli/manage.py` carried over from CP1 —
unchanged.

Ruff:

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_server
All checks passed!
$ .venv/bin/python3.12 -m ruff format --check packages/llm_tracker_server
12 files already formatted
```

Ruff applied a small autofix pass during CP2 — three I001 import-sort
fixes and a one-line reflow in `test_storage_smoke.py`. No structural
changes; lockfile clean.

Cleanup: ephemeral container torn down with
`docker rm -f llm-tracker-pg-cp2`.

### CP1

`uv sync` clean; the now-unused `pynacl` + `keyring` + transitive
`cffi`/`pycparser`/`jaraco-*`/`more-itertools` chain was uninstalled
in the same pass.

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
.                                                                        [100%]
1 passed in 0.14s
```

Full repo suite (sanity — no regression from the new testpath or
the workspace re-sync):

```
$ .venv/bin/python3.12 -m pytest -q
...
249 passed, 4 warnings in 7.04s
```

The four warnings are the pre-existing `DeprecationWarning: fork()`
from `llm_tracker/cli/manage.py`, unchanged.

Ruff:

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_server
All checks passed!
$ .venv/bin/python3.12 -m ruff format --check packages/llm_tracker_server
6 files already formatted
```

Single autofix applied during CP1: `ruff check --fix` collapsed the
blank line between third-party and `llm_tracker_server` imports in
`tests/test_healthz.py`. Ruff treats `llm_tracker_server` as
third-party (no `known-first-party` config in the workspace
`pyproject.toml`); this is consistent with how the existing
packages structure their imports, so no config change is needed.

Manual boot check (representative — not re-run for every checkpoint):

```
$ .venv/bin/python3.12 -c "from llm_tracker_server.app import app; print(app)"
<fastapi.applications.FastAPI object at 0x...>
```

The healthz endpoint is exercised by the pytest above; running
`uvicorn` against a free port and `curl`ing it would just duplicate
the ASGI-transport test, so I skipped the live-port loop.

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

CP3 landed cleanly. Source `HEAD` is `373ed11`; the §5.3 finalize
commit refreshing `docs/STATUS.md` + this worklog adds one more.
The 14-checkpoint plan is **3/14 done**.

**Next single step**: **CP4 — `org_id NOT NULL` on the four user-data
tables (ADR-0018 tenancy).** Per the plan:

- New migration
  `packages/llm_tracker_server/alembic/versions/0004_org_id_on_user_data.py`
  adding `org_id UUID NOT NULL REFERENCES orgs(id)` to `exchanges`,
  `events`, `tool_calls`, `audit_log`. No backfill — greenfield
  server-side schema; the CP9-of-supabase-sink demo rows are
  operator data and drop/recreate under the new shape.
- Update the four ORM models in
  `packages/llm_tracker_server/src/llm_tracker_server/storage/models.py`
  to carry the same column, typed as `postgresql.UUID(as_uuid=True)`
  matching CP3's choice. No FK relationship object needed yet —
  CP5's RLS policies are the authority, not SA's session-level
  cascade.
- New `tests/test_org_id_constraint.py` pinning both rejections:
  inserting without `org_id` fails the NOT NULL constraint;
  inserting with a UUID that does not appear in `orgs` fails the FK.
  Same skipif-without-`LLMTRACK_TEST_DATABASE_URL` pattern as CP2/CP3.
- Still **no RLS policies and no auth** — those land in CP5/CP6.
  Defense-in-depth comes from the column constraint plus the
  policy; CP4 is the constraint half.

For a future session reviving the dev loop:

```
docker run -d --name llm-tracker-pg \
  -e POSTGRES_USER=cp2 -e POSTGRES_PASSWORD=cp2 \
  -e POSTGRES_DB=llm_tracker_test \
  -p 55432:5432 postgres:15
export LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test
```

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
   of the signing-removal worklog). *Resolved in CP1.*
5. **Dockerfile / Fly deploy will need the alembic CLI shipped in
   the runtime image** so the release-command migration runner
   (CP13) works. Trivial to add but worth flagging here so it
   doesn't surprise CP12.
6. **Share the alembic upgrade/downgrade fixture via a server-package
   `conftest.py`** once CP4's smoke test lands. CP3 copy-pasted the
   subprocess wrapper from CP2's `test_storage_smoke.py`; with CP4
   it becomes three copies, which is the right point to hoist.
