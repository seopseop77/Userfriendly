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

### CP9 — Storage layer: org-aware INSERTs (2026-05-12, commit `fe18e9a`)

- New `packages/llm_tracker_server/src/llm_tracker_server/storage/exchanges.py`
  — two helpers:
  - `record_exchange_timing(session, *, exchange_id, org_id,
    endpoint, t_request_received_ms, t_upstream_first_byte_ms,
    t_client_first_byte_ms)` — happy path, called after the
    upstream SSE stream finishes cleanly.
  - `record_exchange_blocked(session, *, exchange_id, org_id,
    endpoint, blocked_by, started_at_ms)` — short-circuit path,
    called for `Block` from `on_request_received` /
    `before_forward` and `Abort` from
    `on_upstream_response_start`.
  - Both helpers set `org_id` on the column explicitly (defense
    in depth on top of CP5's RLS `WITH CHECK`) and `flush` —
    *not* `commit` — so the per-request session retains
    transaction control.
- New `packages/llm_tracker_server/src/llm_tracker_server/storage/audit.py`
  — single `write_audit(session, *, org_id, kind, outcome,
  plugin, hook, capability, destination, detail_json)` helper.
  Same flush-not-commit posture; the append-only triggers from
  migration `0002_audit_log_triggers` make every flushed row
  permanent once the request transaction commits.
- New `packages/llm_tracker_server/src/llm_tracker_server/audit_context.py`
  — request-scoped audit plumbing:
  - `bind_request_context(session, org_id)` — sync `with` that
    sets a `ContextVar` for the duration of the block.
  - `session_bound_audit_writer(**kwargs)` — production audit
    writer that reads the contextvar and forwards to
    `write_audit`. Silently no-ops outside a request scope so
    lifecycle audits fired from `PluginHost.on_init` /
    `on_shutdown` don't crash trying to write an org-less row.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/storage/__init__.py`
  to re-export the three new helpers (`record_exchange_blocked`,
  `record_exchange_timing`, `write_audit`).
- Modified `packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py`:
  - Reads `request.state.session` + `request.state.org_id` (when
    `AuthMiddleware` ran). Wraps the pre-streaming hook calls
    + `record_exchange_blocked` writes in
    `bind_request_context(session, org_id)`.
  - Each of the three `Block` / `Abort` short-circuit paths
    calls `record_exchange_blocked(session, ..., org_id=org_id)`
    before `return block_response(...)`. The row carries
    `blocked_by = result.plugin` + `endpoint = path` so audits
    can attribute the decision.
  - The response generator opens a **fresh** `AsyncSession`
    from `request.app.state.session_factory` for post-stream
    writes. Under `starlette.middleware.base.BaseHTTPMiddleware`
    the auth middleware's terminal `session.commit()` runs
    *before* the outer ASGI layer iterates the streamed body,
    so the request-scoped session is closed by the time
    `record_exchange_timing` would fire. The generator
    re-issues `SET LOCAL ROLE llm_tracker_app` +
    `set_config('app.org_id', :uuid, true)` on the fresh
    session, binds the audit context to it, calls
    `record_exchange_timing` between `on_response_complete` and
    `on_persisted`, then `commit`s. Both lifecycle paths land
    inside one `AsyncExitStack` for readability.
  - The generator's `request.scope.get("app")` lookup of
    `session_factory` is defensive: the CP7/CP8 forwarder unit
    tests build a bare `Request` with no `app` in scope, so the
    storage wiring no-ops back to the transparent shape there.
  - `plugin_host=None` and no-request-scope shapes both remain
    byte-for-byte the CP7/CP8 transparent passthrough — gated
    on `has_post_stream_storage` which folds three pre-existing
    conditions (request scope + session factory + plugin host)
    into one branch.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/app.py`:
  - Lifespan now constructs `EgressGuard` + `PluginHost` with
    `audit_writer=session_bound_audit_writer`, so audit rows
    land in the request-scoped session every time the
    contextvar is bound.
  - Lifespan stashes the session factory on
    `app.state.session_factory` so the forwarder's generator
    can open the fresh post-stream session.
- New `packages/llm_tracker_server/tests/test_two_org_e2e_isolation.py`
  (1 case, PG-required) —
  `test_two_org_e2e_isolation`: seeds two orgs + tokens, drives
  a POST `/v1/messages` through the real catch-all as org A
  (upstream mocked via `httpx.MockTransport` +
  `monkeypatch.setattr(forwarder, "UPSTREAM_BASE", ...)`), then
  asserts:
  - As org A: exactly one `exchanges` row, `org_id = org_A`,
    `endpoint = "v1/messages"`, `blocked_by IS NULL`.
  - As org B: zero rows (CP5 RLS isolation).
  - As `app.role = 'admin'`: one row total (the admin policy
    branch, no service-role bypass).
- The test bypasses FastAPI lifespan and seeds `app.state`
  manually (`upstream_client`, `plugin_host`, `session_factory`)
  so the FastAPI catch-all reaches `forward_request` with all
  three contracts wired without paying for a real `httpx`
  client lifecycle per test.



- New `packages/llm_tracker_server/src/llm_tracker_server/plugin_host/`
  package with four modules:
  - `host.py` — `PluginHost` class ported from the local sidecar with
    three shape changes mandated by ADR-0019 and the CP8 plan:
    (i) `mode=` is dropped; (ii) `user_opted_in=` is dropped; (iii)
    `session_factory=` is replaced by an injected `AuditWriter`
    callable that defaults to a no-op. Lifecycle (load → on_init →
    per-request hooks → on_shutdown), entry-point loading, manifest
    parse + denylist (`plugins_disabled`), per-plugin
    `HostEgressClient` binding, timeout + exception isolation, and
    the `loaded_plugins()` introspection view are all preserved.
  - `context.py` — `make_hook_context(...)` is the single chokepoint
    that builds per-exchange `HookContext` instances. The SDK
    dataclass still encodes the legacy L/A/R-mode ceiling, so for
    CP8 the factory passes `mode="R"` + `user_opted_in=True` —
    yielding L3 visibility — as a transitional shape until CP10's
    `min_content_level` manifest field introduces per-plugin
    clamping. Flagged in `Decisions §CP8`.
  - `manifest.py` — `find_manifest(plugin_class)` walks
    `importlib.resources` for the plugin's top-level package and
    parses `plugin.toml` against `PluginManifest` (SDK schema). The
    `allowed_modes` field passes validation but the server-side
    host *ignores* the value entirely (ADR-0019).
  - `hooks.py` — exposes `HOOK_TIMEOUT = 5.0` and
    `SHUTDOWN_HOOK_TIMEOUT = 30.0`. The shutdown budget is the same
    30 s carry-over from the supabase_sink prerequisite (so a sink
    drain doesn't fault under the per-exchange 5 s budget).
  - `__init__.py` re-exports `PluginHost`, `AuditWriter`,
    `make_hook_context`, and the two timeout constants.
- New `packages/llm_tracker_server/src/llm_tracker_server/egress_guard/`
  package with two modules:
  - `guard.py` — `EgressGuard` ported with two shape changes:
    (i) `mode=` is dropped (ADR-0019); the mode-keyed denial paths
    (`mode_L_denies_egress`, `mode_X_not_in_allowed_modes`,
    `mode_A_requires_single_destination`) are gone. (ii) Audit
    writes route through an injected `AuditWriter` callable instead
    of opening a fresh session from a session factory. What
    remains: manifest registration, capability declaration check
    (`capability_not_declared:<name>`), exact-URL allowlist
    (`destination_not_in_allowlist`).
  - `client.py` — `HostEgressClient` ported verbatim (ADR-0015 is
    untouched by ADR-0019; same per-plugin binding contract).
  - `__init__.py` re-exports `EgressGuard`, `HostEgressClient`,
    `AuditWriter`.
- New `packages/llm_tracker_server/src/llm_tracker_server/content_levels/`
  package with a single `levels.py` re-export of the SDK content-
  level primitives. The host has no other call sites for the
  ceiling math in CP8; the package is laid down so CP10's clamping
  has a stable internal home.
- New `packages/llm_tracker_server/src/llm_tracker_server/proxy/sse.py`
  — the synthetic Anthropic block stream from ADR-0002 §3:
  `block_sse_chunks(reason, exchange_id)` returns the exact byte
  sequence (`message_start` → `content_block_start` →
  `content_block_delta` with `[llm-tracker] <reason>` →
  `content_block_stop` → `message_delta` → `message_stop`), and
  `block_response(reason, exchange_id, plugin_host)` wraps it as a
  `StreamingResponse` whose `gen()` finally-block calls
  `plugin_host.end_exchange(exchange_id)` so the per-exchange ctx
  is dropped on the Block / Abort path too.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py`
  to wrap the CP7 surface with the 8-hook plugin lifecycle:
  `plugin_host` is a new keyword-only argument; when supplied,
  `forward_request` calls `begin_exchange` → `on_request_received`
  → `before_forward` (with `Block` / `Transform` honoured) →
  `on_upstream_response_start` (with `Abort` honoured) → streams
  chunks with `on_response_chunk` (Abort cuts mid-stream) →
  `on_response_complete` + `on_persisted` on a clean upstream EOF
  → `end_exchange` in the generator's outer finally. The
  `async for ... else` idiom gates the completion hooks so an
  Abort-on-chunk truncation does *not* fire them (this fixes a
  pre-existing flaw in the local-sidecar version where `completed
  = True` ran after `break`; flagged in Decisions §CP8). When
  `plugin_host=None` the forwarder is the CP7 transparent shape
  byte-for-byte.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/proxy/__init__.py`
  to re-export `block_response` and `block_sse_chunks` alongside
  the existing CP7 surface.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/app.py`
  (the FastAPI factory) — `lifespan` now owns two `httpx.AsyncClient`
  instances (one for upstream forwarding, one for plugin egress;
  mirrors the local-sidecar split), builds an `EgressGuard` + a
  `PluginHost`, calls `on_init()`, and attaches them to
  `app.state.{plugin_host, egress_guard, upstream_client}`. On
  shutdown: `PluginHost.on_shutdown()` runs *before* the egress
  client closes so a shutdown-time flusher (e.g. supabase_sink)
  can still reach its sink. Two new routes are mounted when the
  session factory is available: `/admin/plugins` (ADR-0014
  introspection) and the catch-all
  `@app.api_route("/{path:path}", methods=[DELETE/GET/PATCH/POST/PUT])`
  that calls `forward_request(...)` with the lifespan-owned
  upstream client and the `plugin_host`. The catch-all is
  registered *after* `/healthz` / `/admin/whoami` /
  `/admin/plugins` so FastAPI's in-order dispatch reaches the
  named routes first. The bare `/healthz` boot contract from CP1
  is preserved: with no `LLMTRACK_DATABASE_URL` and no injected
  factory, `create_app()` still returns a `FastAPI` with
  `/healthz` and nothing else.
- New `packages/llm_tracker_server/tests/test_plugin_host.py`
  (15 cases, no PG fixture) — ported from
  `packages/llm_tracker/tests/test_plugin_host.py` and reshaped to
  the injected-audit-writer model:
  - Lifecycle audits: `test_on_init_emits_proxy_started`,
    `test_per_exchange_hooks_emit_hook_invoked`,
    `test_on_shutdown_emits_proxy_stopped`.
  - Fault isolation:
    `test_crashing_plugin_does_not_propagate`,
    `test_timeout_plugin_does_not_propagate`.
  - Shutdown budget:
    `test_on_shutdown_uses_longer_timeout_than_per_exchange_hooks`,
    `test_on_shutdown_still_faults_past_shutdown_timeout`.
  - Manifest validation:
    `test_load_plugins_rejects_missing_manifest`.
  - Egress wiring:
    `test_load_plugins_registers_manifest_with_egress_guard` —
    asserts `EgressGuard._manifests` is populated and a subsequent
    `check()` emits an `egress_attempt` row through the same
    audit writer.
  - ADR-0019 retirement:
    `test_load_plugins_no_longer_mode_gates_egress_http` — a
    manifest declaring `egress_http` loads without any
    `capability_denied` row, regardless of (now-ignored)
    `allowed_modes`.
  - Disable-by-config: `test_load_plugins_skips_disabled_by_config`.
  - Introspection: `test_loaded_plugins_returns_serialisable_view`.
  - HookContext lifecycle:
    `test_begin_exchange_passes_same_ctx_to_each_hook`,
    `test_dispatcher_falls_back_to_default_ctx_when_no_begin_exchange`,
    `test_end_exchange_drops_ctx`. The first asserts
    `request_text(L3)` returns the full body — the CP8
    transitional permissive shape (Decisions §CP8 D1).
- New `packages/llm_tracker_server/tests/test_egress_guard.py`
  (7 cases, no PG) — ported denial + allow paths sans the mode-keyed
  variants retired by ADR-0019:
  - Denials: `test_unregistered_plugin_denied`,
    `test_missing_capability_denied`,
    `test_destination_not_in_allowlist_denied`.
  - Allows: `test_single_destination_match_allowed`,
    `test_multiple_destinations_each_match_allowed` (pins that
    the prior Mode-A single-destination rule is gone),
    `test_register_overwrites_previous_manifest`,
    `test_exact_match_no_wildcards`.
- New `packages/llm_tracker_server/tests/test_proxy_forwarder_hooks.py`
  (7 cases, no PG) — integration coverage for the new wiring:
  - `test_block_on_request_received_short_circuits_upstream` —
    upstream is never called; the synthetic block stream is
    returned; `_exchange_contexts` is empty after drain.
  - `test_block_on_before_forward_short_circuits_upstream`.
  - `test_transform_in_before_forward_rewrites_outbound` —
    plugin-supplied headers + body land on the outbound request;
    the credential header alongside survives.
  - `test_abort_on_upstream_response_start_emits_block_stream` —
    upstream WAS called (Abort here fires after the response
    headers are seen), but its body is replaced with the synthetic
    block stream.
  - `test_happy_path_dispatches_every_hook_in_order` — pins the
    strict prefix (`on_request_received` → `before_forward` →
    `on_upstream_response_start`), at least one
    `on_response_chunk`, and the strict suffix
    (`on_response_complete` → `on_persisted`).
  - `test_abort_on_response_chunk_skips_remaining_hooks` — the
    `async for ... else` gate keeps `on_response_complete` and
    `on_persisted` from firing on a truncated stream.
  - `test_no_plugin_host_is_transparent_passthrough` — CP7 shape
    survives byte-for-byte when no `plugin_host` is wired.

### CP7 — Anthropic credential pass-through + log scrubbing (2026-05-12, commit `e1d34bc`)

- New `packages/llm_tracker_server/src/llm_tracker_server/proxy/`
  package with three modules:
  - `credential.py` — `CREDENTIAL_HEADER_NAMES = {"x-api-key",
    "anthropic-api-key"}` (lowercase; HTTP header lookups are
    case-insensitive). `is_credential_header(name)` is the
    case-insensitive predicate. `scrub_credential_processor` is a
    structlog processor that recursively walks the event dict and
    replaces any value under a credential-header key with
    `[REDACTED]`, and *also* replaces any string value beginning with
    `sk-ant-` regardless of which key carries it — defends against
    accidental dumps into exception strings, header `repr()`, or a
    careless future call site. Returns a *new* dict so the original
    event payload (held only by structlog at this point) is left
    intact for callers that may still need it.
  - `forwarder.py` — `forward_request(request, path, *, http_client,
    upstream_base=UPSTREAM_BASE)`. Reads the inbound body once, builds
    an outbound header set by stripping hop-by-hop headers (`host`,
    `content-length`, `transfer-encoding`, `connection`,
    `accept-encoding`) plus the local-only `authorization` (which was
    consumed by `AuthMiddleware` and would either be rejected by
    Anthropic or, worse, logged upstream), then issues
    `http_client.build_request(...)` + `http_client.send(stream=True)`
    and yields the upstream chunks back via a `StreamingResponse`.
    Emits a structured `proxy.forward` log with `method`, `path`, and
    a boolean `forwarded_credential` flag — the audit signal an
    operator can grep for without ever materialising the credential
    bytes.
  - `__init__.py` — re-exports `CREDENTIAL_HEADER_NAMES`, `REDACTED`,
    `UPSTREAM_BASE`, `forward_request`, `is_credential_header`,
    `scrub_credential_processor`. Module docstring also pins CP7's
    scope: credential passthrough only; CP8 owns the catch-all route
    wiring + plugin host + SSE Tee port.
- `packages/llm_tracker_server/src/llm_tracker_server/logging.py` —
  inserts `scrub_credential_processor` into the structlog chain just
  before the JSON renderer, so every emitted event passes through the
  scrubber regardless of which call site wrote it.
- `packages/llm_tracker_server/pyproject.toml` — promoted `httpx`
  from `[dependency-groups] dev` to `[project] dependencies`; it is
  now a runtime dep (the forwarder needs it in production, not just
  in tests).
- New `packages/llm_tracker_server/tests/test_credential_passthrough.py`
  pins nine assertions (none of which require PostgreSQL — the
  credential surface is DB-free, and the proxy uses `httpx.MockTransport`
  to capture the outbound request):
  - `test_outbound_carries_x_api_key` — inbound `x-api-key`
    reaches the upstream request unchanged; URL and method are
    correct.
  - `test_outbound_carries_anthropic_api_key_alternate` — the
    documented alternate name `anthropic-api-key` also passes
    through (Anthropic accepts both).
  - `test_outbound_strips_authorization_bearer` — the llm-tracker
    Bearer is *not* forwarded; the Anthropic credential alongside it
    still is.
  - `test_query_string_is_preserved` — query strings round-trip
    intact in the outbound URL.
  - `test_scrub_processor_redacts_credential_header_key` — top-level
    `x-api-key` / `anthropic-api-key` / mixed-case variants are all
    redacted; non-credential keys are untouched.
  - `test_scrub_processor_redacts_nested_credential_header` — a
    credential key inside a nested `headers` dict is redacted.
  - `test_scrub_processor_redacts_secret_value_anywhere` — an
    `sk-ant-...` string under a non-credential key (or inside a
    nested list) is redacted by the value-prefix rule.
  - `test_scrub_processor_does_not_mutate_input` — the processor
    returns a new dict; the caller's event payload is preserved.
  - `test_configured_logging_chain_redacts_credential_from_stdout` —
    end-to-end: run `configure_logging("INFO")`, emit a structured
    log call that includes the credential in three different shapes
    (top-level key, nested header dict, raw value), capture the
    rendered JSON, assert the credential bytes never appear and the
    `forwarded_credential` audit signal does.

### CP6 — Auth middleware + tokens CLI (2026-05-12, commit `1c0835a`)

- New `packages/llm_tracker_server/src/llm_tracker_server/auth/`
  package with three modules:
  - `tokens.py` — pure helpers. `hash_token(plaintext) -> sha256 hex`
    is the only hashing primitive used by both the middleware lookup
    path and the CLI issuance path. `generate_plaintext()` mints
    `lts_` + `secrets.token_urlsafe(32)`. `lookup(session, plaintext)`
    returns an `ApiToken` row or `None`, filtered by
    `revoked_at IS NULL` so an active and revoked status look the
    same to callers. `issue(session, *, org_name, token_name=None)`
    returns `(plaintext, org_id, token_hash)` and creates the `Org`
    on demand. `revoke(session, *, token_hash)` is rowcount-based and
    idempotent-safe (re-revoke returns `False`). `list_for_org` joins
    `api_tokens` + `orgs` for the CLI.
  - `middleware.py` — `AuthMiddleware(BaseHTTPMiddleware)`. Bypasses
    `/healthz` (configurable; defaults to `{"/healthz"}`); parses
    `Authorization: Bearer <token>` returning 401 on missing or
    malformed scheme; hashes the plaintext, opens a request-scoped
    session, issues `SET LOCAL ROLE llm_tracker_app` then `SELECT
    set_config('app.org_id', '<uuid>', true)`, and attaches
    `request.state.org_id` + `request.state.session` for downstream
    handlers. On `lookup` miss returns 403 with the "unknown or
    revoked token" message (statuses conflated so the response
    cannot probe revocation state). Commits the session after the
    downstream handler returns.
  - `__init__.py` — re-exports the helpers + the middleware class
    for the rest of the package.
- New `packages/llm_tracker_server/src/llm_tracker_server/cli/` with
  a Typer entry point:
  - `main.py` declares `app = typer.Typer(...)` with a `tokens`
    subtree of `issue`, `revoke`, `list`. `_session_scope()` is a
    shared async context manager that loads `.env`, reads
    `LLMTRACK_DATABASE_URL`, builds an engine + factory, yields a
    session, and disposes the engine on exit. `tokens issue` prints
    `org_id=`, `token_hash=`, `token=` on stdout and a "store this
    token now — it cannot be recovered" hint on stderr; the
    plaintext is shown only on a successful commit.
  - `__init__.py` is a docstring-only file. Re-exporting `app` from
    `.main` would trigger a `runpy` warning under
    `python -m llm_tracker_server.cli.main`; the production console
    script targets `llm_tracker_server.cli.main:app` directly, so the
    re-export gains nothing.
- `packages/llm_tracker_server/pyproject.toml` — added `typer` to
  `[project] dependencies` and declared the console script
  `llm-tracker-server = "llm_tracker_server.cli.main:app"` under a
  new `[project.scripts]` table.
- `packages/llm_tracker_server/src/llm_tracker_server/app.py` —
  `create_app` now takes an optional `session_factory` parameter. If
  one is passed, it is used as-is (the test path injects the CP5
  `conftest.py` factory). If `session_factory is None` *and*
  `settings.database_url` is set, the factory wires `make_engine` +
  `make_session_factory` and disposes the engine on lifespan exit.
  If a factory is available (either path), the factory registers
  `AuthMiddleware` and a small `/admin/whoami` route that returns
  `{"org_id": str(request.state.org_id), "app_org_id_setting":
  current_setting('app.org_id', true)}` (read off
  `request.state.session`). With no DB URL and no injected factory,
  the app boots `/healthz`-only, preserving the CP1 contract.
- `packages/llm_tracker_server/src/llm_tracker_server/storage/__init__.py`
  and `.../storage/models.py` docstrings updated to point at CP6
  landing the per-request `SET LOCAL ROLE` + `app.org_id` binding
  (was previously deferred to CP6/CP9; CP9 still owns routing
  storage INSERTs through the same session).
- New `packages/llm_tracker_server/tests/test_auth_middleware.py`
  pins five HTTP cases against a real PostgreSQL:
  - `test_missing_authorization_returns_401` — no Bearer →
    401 before any DB lookup.
  - `test_unknown_token_returns_403` — a freshly generated
    plaintext (never persisted) → 403.
  - `test_valid_token_binds_org_axis` — seed an `Org` + `ApiToken`,
    hit `/admin/whoami` with the plaintext Bearer, assert 200 and
    that both `org_id` and `app_org_id_setting` in the JSON match
    `str(uuid.UUID(<assigned id>))`.
  - `test_healthz_is_public` — `/healthz` returns 200 with no
    Authorization even when auth is wired.
  - `test_revoked_token_returns_403` — seed a token with
    `revoked_at = now()`, assert 403 with the same shape as the
    unknown-token case.

### CP5 — RLS policies + `llm_tracker_app` role (2026-05-12, commit `0dec2f1`)

- New migration
  `packages/llm_tracker_server/alembic/versions/0005_rls_policies.py`
  does three things in order:
  1. `CREATE ROLE llm_tracker_app NOLOGIN` (guarded by `DO $$ IF NOT
     EXISTS`) plus `GRANT USAGE ON SCHEMA public` and
     `GRANT SELECT, INSERT, UPDATE, DELETE` on the four user-data
     tables and the two substrate tables. The role is non-superuser
     and has no BYPASSRLS — that is the whole point. Production
     deploys add LOGIN; tests `SET LOCAL ROLE` into it.
  2. `ALTER TABLE … ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL
     SECURITY` on each of `exchanges`, `events`, `tool_calls`,
     `audit_log`.
  3. Two PERMISSIVE policies per table (OR-combined):
     - `<table>_org_isolation` (FOR ALL): `org_id = NULLIF(
       current_setting('app.org_id', true), '')::uuid` on both USING
       and WITH CHECK.
     - `<table>_admin_access` (FOR ALL): `NULLIF(current_setting(
       'app.role', true), '') = 'admin'` on both USING and WITH
       CHECK.
- `packages/llm_tracker_server/src/llm_tracker_server/storage/__init__.py`
  docstring extended to point at CP5 landing RLS (and to note that
  per-request `SET LOCAL app.org_id` is still CP6's responsibility).
- New `packages/llm_tracker_server/tests/conftest.py` hoists the
  alembic upgrade/downgrade subprocess + `session_factory` fixture
  out of three copy-pasted bodies (CP2 / CP3 / CP4) and wraps the
  raw SQLAlchemy sessionmaker in an async context manager that
  issues `SET LOCAL ROLE llm_tracker_app` on every session. Without
  that wrap, the docker-default `POSTGRES_USER=cp2` superuser would
  bypass RLS unconditionally and the isolation test would never
  fail (see Decisions §CP5).
- New `packages/llm_tracker_server/tests/test_rls_two_org_isolation.py`
  pins five visibility assertions plus one write-path assertion:
  - `test_two_org_isolation` — bound to org A, insert 2 exchanges;
    bound to org B, `SELECT count(*)` returns 0; bound back to org
    A, count = 2; admin (no `app.org_id`, `app.role = 'admin'`),
    count = 2; unbound, count = 0 (default-closed).
  - `test_cross_org_write_rejected` — bound to org A, attempting to
    insert a row with `org_id = B` raises
    `sa.exc.ProgrammingError` with message containing
    `row-level security`.
- `packages/llm_tracker_server/tests/test_storage_smoke.py` updated:
  both round-trip and append-only tests now `SELECT set_config(
  'app.org_id', :v, true)` after the `Org` flush, before touching
  user-data tables. The shape is identical to what CP6's auth
  middleware will issue.
- `packages/llm_tracker_server/tests/test_org_id_constraint.py`
  updated: each insert runs under `set_config('app.role', 'admin',
  true)` so the admin policy branch admits the WITH CHECK and the
  test focuses on the column-level constraints it was written to
  pin (NOT NULL, FK). RLS as a separate gate is covered by the new
  isolation test.
- `packages/llm_tracker_server/tests/test_org_token_models.py`
  updated only at the import/fixture surface — `orgs` and
  `api_tokens` have no RLS, so no per-test setting is needed.

### CP4 — `org_id NOT NULL` on the four user-data tables (2026-05-11, commit `2da7438`)

- New migration
  `packages/llm_tracker_server/alembic/versions/0004_org_id_on_user_data.py`
  adds `org_id UUID NOT NULL REFERENCES orgs(id)` to `exchanges`,
  `events`, `tool_calls`, `audit_log`. Iterates the four tables with
  a shared `for ...` loop — the column shape is identical on every
  table and a loop keeps the migration body honest about it. No
  backfill (greenfield server-side schema; CP9 of supabase-sink is
  operator demo data and is recreated against the new shape).
- `packages/llm_tracker_server/src/llm_tracker_server/storage/models.py`
  gains a matching `org_id: Mapped[uuid.UUID]` column on each of
  `Exchange`, `Event`, `ToolCall`, `AuditLog`. Typed as
  `postgresql.UUID(as_uuid=True)` with `ForeignKey("orgs.id")` and
  `nullable=False`, matching CP3's dialect choice. No SA `relationship`
  object — RLS policies (CP5) are the cross-org authority, not SA's
  session-level cascade.
- `storage/__init__.py` docstring updated to point at CP4 landing
  the column; CP5/CP6 still own RLS + per-request `SET LOCAL
  app.org_id`.
- New `tests/test_org_id_constraint.py` pins both rejections:
  - `test_exchange_without_org_id_rejected` — insert without
    `org_id` raises `sa.exc.IntegrityError` (NOT NULL violation).
  - `test_exchange_with_unknown_org_id_rejected` — insert with a
    random UUID raises `sa.exc.IntegrityError` (FK violation).
- `tests/test_storage_smoke.py` updated for CP4: both round-trip
  and append-only tests now create an `Org` first, flush, and
  attach `org_id` to the Exchange/AuditLog insert. The Exchange
  round-trip also re-asserts `org_id` survives the round trip.

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

### CP9

- **D1 — Generator opens a *fresh* `AsyncSession` for post-stream
  writes; the auth middleware's request-scoped session is only used
  for pre-stream writes.** Under
  `starlette.middleware.base.BaseHTTPMiddleware`, the dispatch
  function returns the response wrapper *before* the outer ASGI
  layer iterates the body — and `async with session_factory()`
  inside the middleware exits the moment `dispatch` returns, so
  the session is closed by the time `forward_request`'s response
  generator's post-completion hook runs. Reusing
  `request.state.session` in the generator would hit
  `ResourceClosedError` (or, observed first, hang the test under
  the anyio task-group queue back-pressure). The plan said to use
  the middleware's session; the middleware's lifecycle under
  `BaseHTTPMiddleware` makes that physically impossible for the
  streaming body. CP9 splits the write surface: pre-stream
  (blocked-row INSERT + every hook audit fired before `return
  StreamingResponse(...)`) lands on the middleware's session;
  post-stream (timing-row INSERT + chunk-loop / completion audits)
  lands on a fresh session opened inside the generator with the
  same `SET LOCAL ROLE` + `set_config('app.org_id', ...)` axis.
  The cleaner long-term fix is a pure-ASGI replacement of the auth
  middleware that defers `commit()` until after the body
  finishes; flagged in CP8 §D11 already, now blocking a future
  CP9.5 / Phase-3c housekeeping ticket. The split is invisible to
  RLS (both sessions bind the same `app.org_id`); the row hash on
  `exchanges.id` (ULID) cannot collide because the generator runs
  inside the same `forward_request` call that minted the id.

- **D2 — Audit writer is wired through a `ContextVar`, not a
  per-request `PluginHost` parameter.** The `PluginHost` is a
  single shared instance built once in `lifespan`; setting
  `host._audit_writer` per request would race under concurrency.
  The cleanest seam is a contextvar holding `(session, org_id)`
  that the audit writer reads on each invocation: the forwarder
  sets it in the pre-stream `with` block and re-sets it inside
  the generator (the `with` from `forward_request` body exits
  when the function returns, so the generator has to rebind).
  The two `bind_request_context` blocks each carry the session
  that's alive *during* that phase. Outside any request scope
  (`PluginHost.on_init` / `on_shutdown` at app boot), the writer
  reads `None` and no-ops — lifecycle audit emission is a
  deferred Phase-3c carry-over, flagged in Handoff.

- **D3 — `record_exchange_*` and `write_audit` helpers `flush`,
  not `commit`.** The per-request session retains the
  transaction boundary so the auth middleware's terminal
  `session.commit()` is still the single commit point. Same
  posture on the generator's fresh session except the generator
  itself owns the commit on its way out. Letting the storage
  helpers commit mid-request would split one logical request
  into two transactions, which would also reset the
  `SET LOCAL` GUC midway and break the subsequent INSERT's RLS
  context.

- **D4 — Storage layer files mirror the local-sidecar names
  (`exchanges.py` + `audit.py`).** The plan listed
  `exchanges.py`, `events.py`, `tool_calls.py`, `audit_log.py`
  as the touched files. `events.py` and `tool_calls.py` aren't
  needed in CP9 because the Phase-2 extractor hasn't been built
  yet — the only INSERT paths today are the exchange row + the
  audit row. The local-sidecar also stopped at those two files
  for the same reason. The two unused tables stay in the schema
  for the extractor work; this checkpoint doesn't introduce
  helper modules nobody calls.

- **D5 — `session_factory` is plumbed onto `app.state`, not
  threaded through `forward_request` as a parameter.** The
  catch-all route in `app.py` doesn't have a clean way to thread
  a per-app object through to the function it calls;
  `request.app.state` is already the seam used by
  `upstream_client` + `plugin_host`. CP9 follows the same
  pattern. The forwarder reads it via
  `getattr(request.scope.get("app"), "state", None)` so the
  unit-test path that builds a bare `Request` (no `app` in
  scope) keeps working under the CP7/CP8 transparent shape.

- **D6 — `session_bound_audit_writer` is a free function, not
  a method on a singleton.** A free function with module-level
  state (the contextvar lives at module scope) composes more
  cleanly with both `PluginHost` and `EgressGuard` — both take
  a bare callable, no class needed. Adding a singleton would
  have required threading it through `lifespan` and tests
  separately.

- **D7 — The generator's `SET LOCAL ROLE llm_tracker_app` +
  `set_config('app.org_id', ...)` are issued unconditionally on
  the fresh session.** In production the raw
  `async_sessionmaker` needs both; in tests the conftest's
  wrapped factory already drops the role. Issuing both
  unconditionally is idempotent (SQLAlchemy autobegin keeps
  one transaction for the session lifetime; the `SET LOCAL`s
  attach to that transaction and stay attached until commit).

- **D8 — Lifecycle audit rows (proxy_started, plugin_loaded,
  etc.) are silently dropped under CP9.** The audit writer
  reads the contextvar and no-ops outside a request scope.
  The CP4 NOT NULL constraint on `audit_log.org_id` makes
  it impossible to write a "system" audit row without an org;
  ADR-0018 explicitly forbids a service-role bypass. The
  call sites are still in place (CP8 already lifted them
  through the injected writer), so a later checkpoint can
  light them up under whatever shape ADR-#2 dictates
  (operator-org, system-org, separate table, etc.) without
  re-plumbing.

- **D9 — Test bypasses FastAPI lifespan.** The CP9 e2e test
  seeds `app.state` (`upstream_client`, `plugin_host`,
  `session_factory`) manually instead of running the lifespan
  context. Running the lifespan would have spun up a real
  `httpx.AsyncClient` for the upstream (which we then have to
  replace with the mock anyway) and would have fired
  `proxy_started` from the host's `on_init` — which under CP9's
  contextvar shape would be a silent no-op but adds noise to
  the assertion surface. The local-sidecar tests follow the
  same `app.state` seeding pattern.

### CP8

- **D1 — Permissive-by-default `HookContext` is a transitional shape
  for CP8.** The SDK's `HookContext` dataclass still encodes the
  legacy L/A/R-mode ceiling table; `make_hook_context` constructs
  every context with `mode="R"` + `user_opted_in=True`, which the
  SDK resolves to an L3 ceiling. Plugins running on the server see
  the full body until CP10 lands the `min_content_level` manifest
  field + per-plugin clamping. The transitional shape lives in
  `plugin_host/context.py` as a single chokepoint so CP10's swap-
  out is one diff, not a sweep. The alternative (re-shape the SDK
  in CP8 to take an explicit `_ceiling` slot) was rejected because
  the SDK boundary is a public contract (CLAUDE.md §10) and ADR-#2
  may rewrite the ceiling semantics from scratch; better to leave
  the SDK untouched and absorb the clamping inside CP10's
  manifest-validator surface.
- **D2 — `LLMTRACK_USER_OPTED_IN` retired.** The env knob was
  ADR-0016's interim Mode-R consent surface. ADR-0019 retired
  Mode R; the per-org token from CP6 is the new identity anchor;
  the upcoming ADR-#2 will set the consent surface explicitly.
  Keeping the env knob "for now" would silently encode a guess
  about #2's outcome.
- **D3 — `EgressGuard` no longer mode-gates anything.** The three
  denial branches removed (`mode_L_denies_egress`,
  `mode_X_not_in_allowed_modes`, `mode_A_requires_single_destination`)
  were enforcement of the L/A/R taxonomy ADR-0019 retired. What
  remains is the manifest's *own* declaration: capability
  registered + URL exact-match. The `manifest.allowed_modes` field
  is left on the SDK schema for back-compat (existing local-
  sidecar manifests parse cleanly) but is *ignored* by the server
  host. Cleanup of the SDK field is deferred to a later
  housekeeping pass — same posture as `LLMTRACK_USER_OPTED_IN`,
  but on a public-interface schema instead of an env knob.
- **D4 — Audit writes routed through an injected callable
  (`AuditWriter`).** The local-sidecar host opened a fresh
  `AsyncSession` per audit event from a session factory. CP9 needs
  the per-request session (the CP6 middleware-bound one, already
  carrying `app.org_id`) so the audit row is org-tagged; building
  CP9 on top of the local-sidecar shape would have required
  rewiring every call site. Lifting the audit writer to a
  parameter now lets CP9 swap in a session-bound writer without
  changing any call site in `host.py`. CP8 ships a no-op default
  so the host runs without storage access in tests + pre-CP9
  lifespan wiring; the lifecycle audit *call sites*
  (`proxy_started`, `proxy_stopped`, `plugin_loaded`,
  `plugin_fault`, `egress_attempt`, etc.) land here, only the
  writer implementation is stubbed.
- **D5 — `record_exchange_timing` / `record_exchange_blocked` are
  deferred to CP9.** CP9 is the checkpoint that opens a per-
  request session, reads `request.state.{org_id, session}`, and
  writes the `org_id`-tagged exchange row. Bundling the storage
  writes into CP8 would have mixed two distinct safety properties
  (port the proxy vs. org-scope every INSERT) into one commit and
  made the later diff harder to audit. CP8's forwarder hands the
  plugin host the timing values via `on_response_complete` /
  `on_persisted` but writes nothing to the DB itself. Local
  variables `t0_mono`, `t0_epoch_ms`, and the `timing` dict are
  kept (gated by an explicit `_ = (...)` so ruff doesn't flag
  them as unused) — these are the values CP9's `Exchange` row
  payload will read.
- **D6 — `policy.py` is not ported.** The local-sidecar
  `MODE_DENIED_CAPABILITIES` table was the load-time enforcement
  of ADR-0019's retired taxonomy. The new server host accepts
  every declared capability; runtime restrictions (the egress
  allowlist) are `EgressGuard`'s job. Removes one entire failure
  mode from the load path.
- **D7 — The `async for ... else` idiom in the forwarder fixes a
  pre-existing flaw in the local-sidecar version.** The local
  version set `completed = True` unconditionally after the chunk
  loop, which means a `break` (Abort on chunk) still fired
  `on_response_complete` + `on_persisted`. The new server-side
  version moves `completed = True` into the for-loop's `else`
  clause — it runs only when the loop exited naturally. The
  semantic implication is real: a truncated stream is no longer
  "completed", and downstream sinks won't see a misleading
  completion event for it. Flagged here so that if Phase 2's
  Extractor work later assumes the local-sidecar's looser
  behaviour, the divergence is greppable.
- **D8 — The plan's "new `proxy/app.py`" is interpreted as
  modifying the existing top-level `llm_tracker_server/app.py`.**
  The catch-all + lifespan wiring live in `app.py` (the FastAPI
  factory) because splitting them into a sub-module would have
  duplicated the `create_app` surface or required an import
  cycle. Plan §CP8's "Modified: `.../llm_tracker_server/app.py`"
  line was the deciding clue.
- **D9 — Two `httpx.AsyncClient` instances in `lifespan`, not
  one.** The local sidecar already split forwarder from egress
  (different lifetimes — egress closes after `on_shutdown` so a
  flusher can drain). The server preserves the split. Sharing one
  client would have forced a single close ordering on both
  workloads and silently coupled their timeout/HTTP-version
  policies. The forwarder client uses `http2=False` for now
  (Anthropic SSE works fine over HTTP/1.1 and avoids any
  `h2` extra dependency); the egress client uses default
  settings.
- **D10 — The catch-all is gated on the auth middleware being
  wired.** If `create_app()` is called without `LLMTRACK_DATABASE_URL`
  and without an injected `session_factory` (the CP1 boot-with-
  no-DB contract), the catch-all is not registered. Reasoning:
  without the middleware, a request to `/v1/messages` has no
  `request.state.org_id`, and CP9 will need that field on the
  storage write. Better to 404 the path than to forward to
  Anthropic without an identity. The bare `/healthz` boot
  contract from CP1 stays intact.
- **D11 — `BaseHTTPMiddleware` shape of `AuthMiddleware` is
  preserved.** A pure-ASGI middleware would buffer-stream more
  cleanly, but rewriting CP6's middleware is out of scope for
  CP8. Existing CP6 tests pin the current shape; production
  exercise (CP14 smoke) will reveal whether streaming through
  `BaseHTTPMiddleware` actually breaks the `/v1/messages` SSE
  path. If it does, the rewrite is a separate small CP9.5 ticket
  rather than CP8 scope creep.

### CP7

- **`forward_request` takes the `http_client` as an injected
  parameter, not a module-level lazy singleton.** The local-sidecar
  forwarder in `packages/llm_tracker/src/llm_tracker/proxy/forwarder.py`
  uses a process-global `_client` populated on first use; that pattern
  is what makes the existing tests brittle (state leaks across
  parametrisations). Injecting the client lets the CP7 tests use
  `httpx.MockTransport` directly and lets CP8 hand the production
  catch-all a client built inside `lifespan`. The cost is one extra
  parameter per call; the win is that the credential-passthrough
  surface is a pure function of its inputs.
- **The forwarder strips `Authorization` unconditionally** instead of
  pattern-matching the `Bearer lts_…` prefix. The middleware is the
  sole authority for what `Authorization` may carry on an authenticated
  request — by the time the forwarder runs, the only valid value is
  the llm-tracker Bearer that has already been consumed; forwarding
  it would either confuse Anthropic (it expects `x-api-key`) or, if
  Anthropic later started accepting `Bearer`-shaped Authorization,
  leak our token into Anthropic's request logs. A future case where
  the user does want to send `Authorization: Bearer <anthropic-token>`
  (via `ANTHROPIC_AUTH_TOKEN`) can be re-introduced through a separate
  header (e.g. `x-llmtracker-anthropic-bearer`) — not by relaxing the
  strip rule.
- **Scrubber matches by header *name* set + value *prefix*.** The
  name set (`{"x-api-key", "anthropic-api-key"}`) catches the common
  case where a structured log explicitly names the header it is about
  to log. The `sk-ant-` value prefix catches the tail of the leak
  vector: a future contributor pasting `headers.dict()` into an
  exception message, or `repr(request)` showing up in a stacktrace,
  or a debug log emitting `full_headers={...}` under a generic key.
  Together they cover both axes — the operator who knows what they are
  logging *and* the operator who doesn't realise what they're logging.
  Trade-off: the value-prefix rule is bound to Anthropic's current
  API-key format; if Anthropic rotates the prefix, this rule needs
  an additive update.
- **`Authorization: Bearer <anthropic-token>` from the user is not a
  supported configuration in CP7.** The `ANTHROPIC_AUTH_TOKEN` env
  knob Claude Code supports would set `Authorization: Bearer <…>`,
  but our middleware claims that slot. Users must use the `x-api-key`
  path (which is `ANTHROPIC_API_KEY` upstream). Documented inline in
  `proxy/credential.py` and surfaces again at CP11 when `.env.example`
  is refreshed.
- **No DB write, no audit_log row, no `request.state.org_id` read
  in CP7.** The CP7 surface is *only* the credential-passthrough
  edge; CP9 is the checkpoint that wires `org_id`-tagged INSERTs
  through the per-request session. Doing both at once would have
  mixed two distinct safety properties (credential never persisted vs.
  every row scoped to a known org) into one commit and made the
  later diff harder to audit. The `forwarded_credential` boolean is
  the only audit signal the proxy emits in this commit.
- **`scrub_credential_processor` returns a new dict instead of
  mutating in place.** structlog itself doesn't care either way, but
  some upstream processors (especially `merge_contextvars` and any
  test that builds an event dict and inspects it afterwards) hold a
  reference to the pre-render shape. Returning a new dict makes the
  processor side-effect-free at the type level and lets the unit
  test assert non-mutation as a contract.
- **No catch-all route wired in CP7.** The plan reads the CP7 file
  list as proxy/__init__.py + forwarder.py + credential.py — no
  `app.py` change. The forwarder is a callable; CP8 will mount it on
  `/{path:path}` once the plugin host port lands. Wiring it earlier
  would have added one line to `app.py` but would have widened the
  surface of every existing test (the non-`/healthz` non-`/admin/...`
  paths would suddenly try to proxy to Anthropic instead of returning
  404). The current shape keeps the existing test surface
  byte-identical and lets CP8 add the route once.
- **httpx promoted to a runtime dependency.** It was previously
  declared only under `[dependency-groups] dev` because nothing in
  `src/` needed it; CP7 is the first runtime requirement. The
  dev-group entry is intentionally left in place too — it documents
  that the test surface still pulls httpx directly (it would be a
  re-add the moment httpx ever became a runtime-optional dep again).
  pip/uv de-dupes the two declarations; the install footprint is
  unchanged.

### CP6

- **`create_app` takes an injectable `session_factory`.** The
  alternative — letting `create_app` always build the factory from
  `Settings().database_url` — would have forced the test to either
  (a) point the in-process factory at the same docker PG the
  conftest fixture is using, with no way to share the
  fixture's per-test alembic upgrade/downgrade cycle, or (b) ship a
  mock factory and skip the SQL path entirely, which would have
  removed the assertion that `current_setting('app.org_id', true)`
  actually round-trips. Injection lets the test reuse the CP5
  hoisted `session_factory` directly; production still defaults to
  `make_session_factory(make_engine(database_url))` when no factory
  is provided. The shape also keeps the CP1 boot contract: with no
  DB URL and no injected factory, `create_app()` still returns a
  `/healthz`-only app, so `python -c "from llm_tracker_server.app
  import app"` still works on a fresh checkout.
- **Conflated "unknown token" and "revoked token" into one 403.**
  The middleware returns the same `{"detail": "unknown or revoked
  token"}` body in both cases. Distinguishing them at the response
  surface would let an unauthenticated caller probe whether a given
  plaintext was ever issued (and is now revoked) vs never seen at
  all — a low-grade enumeration vector against the token namespace.
  Internally `lookup` filters on `revoked_at IS NULL` directly,
  which is the single source of truth for "is this token currently
  valid?"; revocation is one UPDATE rather than a DELETE so the row
  remains auditable.
- **SHA-256 hex, not a slower KDF.** ADR-0020 §"Token issuance"
  pins the hash primitive to SHA-256. The plaintext is high-entropy
  (32 bytes from `secrets.token_urlsafe`, ~256 bits), so brute-force
  recovery from a DB dump is computationally infeasible at SHA-256
  speed; spending bcrypt/argon2 CPU per request would buy nothing
  against this threat model and would slow every authenticated
  request. The hash function is centralised in `auth.tokens.hash_token`
  so a future migration to a slower KDF is one diff (and matches
  the contract `api_tokens.token_hash TEXT PRIMARY KEY` ADR-0018
  pinned in CP3).
- **`SET LOCAL ROLE` on every request even though `conftest.py`
  already wraps the test factory with the same statement.** The
  middleware is the authority for production; the conftest wrapper
  only exists to make the docker-default `cp2` superuser look like
  the production `llm_tracker_app` role for tests. Running the
  statement twice in a row inside the same transaction is a no-op
  (`SET LOCAL` is idempotent within its transaction scope), so the
  duplicate is harmless. The alternative — letting the middleware
  rely on something the test fixture does — would mean the
  production code path silently depends on a test-only invariant.
- **`request.state.session` exposed as the per-request session.**
  The plan only required `request.state.org_id`. Adding the session
  attribute is what lets the `/admin/whoami` handler read
  `current_setting('app.org_id', true)` off the same session the
  middleware bound — which is the assertion the test relies on to
  prove the GUC actually applies to downstream handlers. CP9 will
  formalise this attribute as the storage entry point; the contract
  the middleware writes here matches the one CP9 will read.
- **`/admin/whoami` route lives in `app.py`, not in a dedicated
  admin router module.** It is currently the only admin route and
  splitting it off would add a `routes/` package whose only job is
  to host one three-line endpoint. CP10's `/admin/plugins`
  introspection (and any other admin routes) will be the right
  point to hoist a shared router; CP6's surface is too thin to
  warrant the structure.
- **`lts_` plaintext prefix.** Purely a self-documenting tag for
  operators reading logs of revocation requests ("this looks like an
  `llm-tracker-server` token, not a Stripe key"). The middleware
  keys on the SHA-256 hash, not the prefix, so a future format
  change does not break anything; existing tokens stay valid until
  they are revoked or rotated.

### CP5

- **Created `llm_tracker_app` as a non-superuser role inside the
  migration itself**, rather than as a deployment-time step. The
  failing-first-attempt smoke (recorded in §Verification §CP5)
  showed that `FORCE ROW LEVEL SECURITY` is not enough on its own:
  Postgres superusers bypass RLS unconditionally, and the
  docker-default `POSTGRES_USER=cp2` is a superuser. The choice was
  between (a) documenting "tests must connect as a non-superuser"
  externally and hoping every contributor wires it correctly, or
  (b) baking the role into the schema. (b) makes the test
  environment look like production (where the app server logs in as
  a non-superuser anyway) and removes a class of "works for me"
  failures. The migration guards the `CREATE ROLE` with
  `DO $$ IF NOT EXISTS` so re-running against a managed PG (or a
  Supabase project that pre-provisions the role) is a no-op.
- **`NULLIF(current_setting('app.org_id', true), '')::uuid` instead
  of the plan's bare `current_setting('app.org_id', true)::uuid`.**
  Once a custom GUC has been touched by any prior transaction in
  the session, Postgres returns `''` (empty string) — not NULL —
  for `current_setting(name, true)` in subsequent transactions
  where it is unset. Casting `''` to UUID raises
  `invalid input syntax for type uuid`, which would tear down the
  "no setting at all → zero rows" assertion in
  `test_two_org_isolation` (the failure showed up on first run; see
  §Verification §CP5 §"First-attempt failures"). `NULLIF(..., '')`
  collapses both shapes into NULL and the `org_id = NULL`
  comparison evaluates to NULL (treated as false), so the
  default-closed semantics hold cleanly. Same shape applied to
  `app.role` for consistency — even though `'' = 'admin'` already
  evaluates to false there, the symmetric form is easier to read
  and matches the pattern the auth middleware should use.
- **Two PERMISSIVE policies per table, not one combined CASE-style
  policy.** The PG idiom for "either of these is sufficient" is two
  PERMISSIVE policies that the planner OR-combines. The
  CASE-inside-a-single-policy form (`USING (CASE WHEN admin THEN
  true ELSE org_id = … END)`) is harder to read, easier to break
  during a future refactor, and obscures from `pg_policies` reads
  that admin is a separate enforcement path. The downside is two
  rows in `pg_policies` per table; well worth it for the read
  clarity.
- **`FORCE ROW LEVEL SECURITY` even though tests now use a
  non-owner role.** Two reasons. First, a future deploy where the
  app role is also the table owner (e.g., a Supabase project where
  the app's own role owns the schema for migration purposes) would
  silently lose RLS without FORCE. Belt-and-braces is cheap. Second,
  it makes the policy intent unambiguous in `\d+ <table>`: "Force
  row security: yes" is one line that tells a reviewer "no, you
  cannot bypass this by being the owner."
- **Admin policy branch is `FOR ALL`, not `FOR SELECT`.** The plan's
  prose said "cross-org SELECT" but the ADR doesn't constrain
  admin's write access. `FOR ALL` keeps the two policies symmetric
  (both per-org and admin admit reads and writes) and matches the
  shape CP6+ admin tooling will want — an admin INSERT into an org
  the operator does not nominally "belong to" is exactly the kind
  of operation operator tooling needs. If we later decide admin
  writes need a stricter shape, the migration to tighten it is one
  `DROP POLICY` + one `CREATE POLICY`.
- **Hoisted the alembic fixture into `conftest.py` AND wrapped the
  session factory in the same step.** The CP4 worklog suggested
  hoisting the fixture in CP5; the RLS test forced the question of
  *what shape* the hoisted fixture should yield. Yielding a raw
  sessionmaker preserved the existing test API but pushed
  `SET LOCAL ROLE llm_tracker_app` into every test body — a
  cross-cutting "every session does this first" piece of setup that
  belongs in the fixture, not the test. The async-context-manager
  wrapper is six lines of conftest.py and keeps test bodies
  focused on the assertion under test.
- **Did not add a `conftest.py`-side per-org seeding helper.** That
  shape was floated by CP4 §Decisions last bullet (and Suggestion
  #6). After writing the RLS test it became clear that "create org
  A and org B, return their IDs" is a single 5-line block inside
  exactly one test — pushing it into the fixture would over-fit a
  shared surface to a single caller. Per-test seeding stays in the
  test file. The hoisted fixture's only cross-cutting concern is
  the role drop, which every PG-touching test needs.
- **Skip-cause refactor**: tests still carry `@pytest.mark.skipif(
  not TEST_DB_URL, …)` decorators alongside the fixture-side
  `pytest.skip()`. The decorator fires *before* fixture setup, which
  means a developer on a machine without PG never sees the
  `_run_alembic("upgrade")` subprocess attempt and never sees its
  error output. Slightly redundant on paper, very useful in
  practice.

### CP4

- **Migration body iterates the four tables in a `for` loop**, not
  four hand-written `op.add_column(...)` blocks. The column shape is
  identical on every table — table name is the only varying input —
  and a loop expresses that more honestly than four duplicated stanzas
  that would invite a future "let's also widen `events.org_id` to
  nullable" drift on one table. The loop body is two lines (one
  `op.add_column`, one `sa.Column(..., ForeignKey, nullable=False)`),
  so the "explicit Python is cheap" tax stays low. Downgrade iterates
  in reverse so the per-step `ALTER TABLE` ordering reads naturally.
- **No SA `relationship()` on either side of the FK.** ADR-0018
  §"Enforcement" makes RLS the single source of truth for cross-org
  visibility, not SA's session-level joinedload/cascade. Adding a
  `relationship(Org, ...)` would let app code traverse `exchange.org`
  *before* RLS short-circuits the query, which is exactly the bypass
  the ADR rules out. The column itself is enough for INSERT-side
  enforcement; SELECT-side enforcement is RLS's job in CP5.
- **No index on `org_id` at any of the four tables.** Mirrors the CP3
  decision for `api_tokens.org_id`: the hot query paths land in CP6
  (auth lookup by `token_hash`, already indexed) and CP9 (per-request
  INSERT, which only touches the row being written). RLS predicates
  generated as `org_id = current_setting('app.org_id', true)::uuid`
  will benefit from a B-tree index once analytics queries arrive;
  add the index in its own migration when CP10+ writes a query that
  actually needs it. Pre-indexing four columns for queries we haven't
  written is exactly the speculative work CLAUDE.md §2.2 rules out.
- **`Exchange.org_id` placed second in the column order** (right
  after the PK), not at the end. Read order in `\d exchanges`
  matters more than schema-evolution diff order here, and putting
  tenancy beside identity is the natural shape — RLS predicates and
  session binding read in that order too. The migration applies
  `ALTER TABLE ... ADD COLUMN` which lands the column at the end on
  disk anyway; the ORM declaration order only affects `SELECT *`
  column order, which the storage layer doesn't rely on.
- **`Exchange` test fixture uses two-step org-then-row insert**
  (add Org → flush → read assigned UUID → add Exchange) rather than
  letting an autoflush handle the FK resolution. The autoflush path
  works, but the explicit `flush()` makes the test's intent visible
  at a glance and matches the shape CP9's request-handler will use
  (open transaction, write org-scoped row, commit).
- **CP2 smoke test updated, not duplicated.** The two existing
  tests (`test_exchange_round_trip`, `test_audit_log_append_only`)
  inserted `Exchange`/`AuditLog` without `org_id` and would now fail
  the NOT NULL constraint. Patching them in place is the minimum
  surgical change that keeps the CP2 verification intact (round-trip
  shape, append-only trigger behaviour) while making them tenancy-aware.
  Splitting "new CP4 test" from "amended CP2 test" preserves the
  defense-in-depth split the plan asks for: CP4 owns the *constraint*
  pin; CP2 still owns the round-trip / trigger pins.
- **Did NOT factor a shared `conftest.py`** in this checkpoint even
  though CP3's Suggestion #6 flagged it. The third copy now exists;
  the right time to hoist is when the fixture grows non-trivially
  (per-org seeding for CP5's RLS isolation test is the obvious
  trigger). Filing forward as a CP5-prep task.

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

### CP7

Targeted run of the new credential-passthrough test file (no PG
needed; the credential surface is DB-free):

```
$ cd packages/llm_tracker_server && \
    ../../.venv/bin/python3.12 -m pytest tests/test_credential_passthrough.py -v
...
9 passed in 0.26s
```

Full server suite without the test URL set:

```
$ ../../.venv/bin/python3.12 -m pytest -q
sssss..........ssssssssss                                                [100%]
10 passed, 15 skipped in 0.29s
```

(The 10 unconditional passes are 1 healthz + 9 new CP7 cases; the 15
skips are the existing CP2 / CP3 / CP4 / CP5 / CP6 PG-only smokes.)

Full repo suite without the test URL set:

```
$ .venv/bin/python3.12 -m pytest -q
...
258 passed, 15 skipped, 4 warnings in 7.71s
```

The 258 unconditional passes are CP6's 249 + the 9 new CP7 cases —
unchanged otherwise, confirming CP7 perturbed neither the
`packages/llm_tracker` historical suite nor the existing server
suite. The 15 PG-only skips are unchanged from CP6 because CP7 added
no PG-dependent test (deliberately — the credential surface does not
touch the database).

Full repo suite with the test URL set (PG container reused from
CP2–CP6 on `localhost:55432`):

```
$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest -q
...
273 passed, 4 warnings in 26.82s
```

273 = 264 (CP6) + 9 (CP7). No skips when the URL is set.

Ruff:

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_server
All checks passed!
$ .venv/bin/python3.12 -m ruff format --check packages/llm_tracker_server
29 files already formatted
```

(One file — `proxy/forwarder.py` — needed one `ruff format` pass at
write time, mostly because the `build_request(...)` line was split
across lines and ruff prefers it on one. The recorded check is
post-format.)

App-import smoke (CP1 boot contract still intact — `create_app` with
no DB URL and no session factory still returns a `/healthz`-only
FastAPI app, and importing the proxy package no longer adds a
required-at-import-time dep beyond httpx, which is now declared):

```
$ .venv/bin/python3.12 -c "from llm_tracker_server.app import app; print('OK', type(app).__name__)"
OK FastAPI
```

Direct credential-leak smoke (re-running just the end-to-end log
chain test under verbose pytest output and asserting the rendered
JSON line manually):

```
$ ../../.venv/bin/python3.12 -m pytest \
    tests/test_credential_passthrough.py::test_configured_logging_chain_redacts_credential_from_stdout -v
PASSED
```

The test captures stdout through a stdlib `StreamHandler` bound to a
`StringIO` so the assertion `ANTHROPIC_SECRET not in rendered`
covers *every* rendered line, not just the JSON payload the test
parses afterwards. The fixture credential string
(`sk-ant-api03-abcdef0123456789`) is intentionally short to keep the
fixture obviously synthetic; it still triggers the `sk-ant-` prefix
match the scrubber relies on. The plan's CP7 verify line also lists a
"manual local test against a stub upstream confirms the header
round-trips and `journalctl`/stdout shows no leakage"; the targeted
test exercises the same code path (forwarder → httpx outbound → log
emission → stdout capture) end to end, so the live-port smoke is
deferred to the CP14 end-to-end checkpoint (which will run uvicorn
against a real Anthropic endpoint anyway).

### CP6

Live PostgreSQL 15.17 container on `localhost:55432`, reused from
CP2–CP5. Targeted run of the new auth-middleware test file:

```
$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_server/tests/test_auth_middleware.py -q
.....                                                                    [100%]
5 passed in 5.79s
```

Full suite with the test URL set (the 5 new CP6 cases land on top
of CP5's 10 PG smokes):

```
$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest -q
...
264 passed, 4 warnings in 23.84s
```

Full suite without the test URL (CI / no-PG developer machines):

```
$ .venv/bin/python3.12 -m pytest -q
...
249 passed, 15 skipped, 4 warnings in 7.48s
```

The 15 skips are 2 CP2 + 4 CP3 + 2 CP4 + 2 CP5 + 5 CP6 PG smokes
— net +5 on the skip total vs. CP5, matching the new
`test_auth_middleware.py` file's five cases. 249 unconditional
passes is unchanged from CP5, confirming CP6 did not perturb the
non-PG suite. The four warnings are the same pre-existing `fork()`
deprecations from `cli/manage.py`.

Ruff:

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_server
All checks passed!
$ .venv/bin/python3.12 -m ruff format packages/llm_tracker_server
25 files left unchanged
```

(One file — `cli/main.py` — needed one `ruff format` pass at write
time; the recorded check is post-format. One `RUF022` `__all__`
not-sorted nit on `auth/__init__.py` auto-fixed with
`ruff check --fix`.)

App-import smoke (CP1 boot contract still intact with no DB URL):

```
$ .venv/bin/python3.12 -c "from llm_tracker_server.app import app; print(app)"
<fastapi.applications.FastAPI object at 0x...>
```

CLI end-to-end smoke against the docker PG (after `alembic upgrade
head`):

```
$ LLMTRACK_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m llm_tracker_server.cli.main tokens issue --org demo
org_id=e9481e70-e182-4974-b768-ed204ec83b45
token_hash=985ed80d34d85e903d22837782de66e82adf4e2b35550393eda1cb3e6fef79e6
token=lts_5pEmSRI1eh-k3nwlt7cAPgVMMagJtJVH73krLRcg6Zo
Store this token now -- it cannot be recovered.

$ ... tokens list --org demo
985ed80d34d8...  org=demo  name=-  status=active

$ ... tokens revoke --hash 985ed80d34d85e903d22837782de66e82adf4e2b35550393eda1cb3e6fef79e6
revoked
```

DB was downgraded to base after the smoke so the next run starts
clean.

The plan's CP6 verification line also lists a `curl
http://localhost:8080/admin/whoami` round-trip against a live
uvicorn process. The pytest `test_valid_token_binds_org_axis` case
exercises the exact same code path through `httpx.ASGITransport`
(routes, middleware, session binding, handler), so the live-port
loop would have duplicated the test rather than added coverage. The
manual `curl` is therefore deferred to the CP14 end-to-end smoke
which will run uvicorn against the staged Supabase URL anyway.

### CP5

Alembic offline-mode SQL gen against the CP5 revision (proves the
DDL is well-formed and the role-creation + grant + enable/force +
two-policy-per-table sequence lands as written):

```
$ LLMTRACK_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m alembic upgrade \
      0004_org_id_on_user_data:0005_rls_policies --sql
...
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'llm_tracker_app') THEN CREATE ROLE llm_tracker_app NOLOGIN; END IF; END $$;
GRANT USAGE ON SCHEMA public TO llm_tracker_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON exchanges, events, tool_calls, audit_log, orgs, api_tokens TO llm_tracker_app;
ALTER TABLE exchanges ENABLE ROW LEVEL SECURITY;
ALTER TABLE exchanges FORCE ROW LEVEL SECURITY;
CREATE POLICY exchanges_org_isolation ON exchanges AS PERMISSIVE FOR ALL TO PUBLIC USING (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid) WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY exchanges_admin_access ON exchanges AS PERMISSIVE FOR ALL TO PUBLIC USING (NULLIF(current_setting('app.role', true), '') = 'admin') WITH CHECK (NULLIF(current_setting('app.role', true), '') = 'admin');
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE events FORCE ROW LEVEL SECURITY;
…  ( same pair of CREATE POLICY for events, tool_calls, audit_log )
UPDATE alembic_version SET version_num='0005_rls_policies' WHERE alembic_version.version_num = '0004_org_id_on_user_data';
COMMIT;
```

Live verification against the same PostgreSQL 15.17 container on
`localhost:55432` reused from CP2/CP3/CP4. Targeted PG-only run
(the new isolation test + the three CP2/CP3/CP4 PG smokes):

```
$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_server/tests/test_rls_two_org_isolation.py \
    packages/llm_tracker_server/tests/test_storage_smoke.py \
    packages/llm_tracker_server/tests/test_org_id_constraint.py \
    packages/llm_tracker_server/tests/test_org_token_models.py -q
..........                                                               [100%]
10 passed in 11.98s
```

Full suite with the test URL set:

```
$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest -q
...
259 passed, 4 warnings in 19.50s
```

Full suite without the test URL (CI / no-PG developer machines):

```
$ .venv/bin/python3.12 -m pytest -q
...
249 passed, 10 skipped, 4 warnings in 7.77s
```

The 10 skips are 2 CP2 + 4 CP3 + 2 CP4 + 2 CP5 PG smokes — net +2
on the skip total versus CP4, matching the new isolation file's two
cases. 249 unconditional passes is unchanged from CP4, which
confirms CP5 did not perturb the non-PG suite. The four warnings
are the same pre-existing `fork()` deprecations from
`cli/manage.py`.

Ruff:

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_server
All checks passed!
$ .venv/bin/python3.12 -m ruff format --check packages/llm_tracker_server
17 files already formatted
```

(The two new files needed one `ruff format` pass at write time; the
recorded `--check` is post-format.)

#### First-attempt failures (worth keeping)

Two failures showed up before the CP5 code landed in its current
shape; recording them so the next reader (or future-me debugging an
analogous issue) sees the root cause and the chosen fix, not just
the green test output:

1. **`FORCE ROW LEVEL SECURITY` alone did not bind a superuser.**
   First-attempt migration enabled and FORCEd RLS but did not
   create the non-superuser app role. Tests ran as the
   docker-default `POSTGRES_USER=cp2`, which is a superuser, and
   Postgres superusers bypass RLS *regardless of FORCE*. Symptom:
   `test_cross_org_write_rejected` produced
   `Failed: DID NOT RAISE <class 'sqlalchemy.exc.ProgrammingError'>`
   — the cross-org INSERT silently succeeded. Fix: the migration
   now also creates `llm_tracker_app` (NOLOGIN, non-superuser) and
   the `conftest.py` fixture wraps every session to issue
   `SET LOCAL ROLE llm_tracker_app` on entry. Captured as Decision
   §CP5 first bullet.
2. **`current_setting('app.org_id', true)` returned `''`, not NULL,
   on later transactions.** Once a custom GUC has been touched in
   any earlier transaction (LOCAL or SESSION), Postgres treats the
   parameter name as defined and returns `''` in subsequent
   transactions where it is unset. Casting `''` to UUID raises
   `invalid input syntax for type uuid`. Symptom:
   `test_two_org_isolation` failed at the "no setting at all
   → zero rows" step with that uuid-cast error. Fix:
   `NULLIF(current_setting('app.org_id', true), '')::uuid` (and
   the symmetric form for `app.role`). Captured as Decision §CP5
   second bullet.

### CP4

Alembic offline-mode SQL gen against the CP4 revision (proves the
DDL is well-formed and the four `ALTER TABLE ... ADD COLUMN ...
NOT NULL` + `ADD FOREIGN KEY` pairs are encoded as written):

```
$ cd packages/llm_tracker_server && \
    LLMTRACK_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/llm_tracker \
    .../python3.12 -m alembic upgrade \
      0003_orgs_and_tokens:0004_org_id_on_user_data --sql
...
-- Running upgrade 0003_orgs_and_tokens -> 0004_org_id_on_user_data

ALTER TABLE exchanges ADD COLUMN org_id UUID NOT NULL;
ALTER TABLE exchanges ADD FOREIGN KEY(org_id) REFERENCES orgs (id);
ALTER TABLE events ADD COLUMN org_id UUID NOT NULL;
ALTER TABLE events ADD FOREIGN KEY(org_id) REFERENCES orgs (id);
ALTER TABLE tool_calls ADD COLUMN org_id UUID NOT NULL;
ALTER TABLE tool_calls ADD FOREIGN KEY(org_id) REFERENCES orgs (id);
ALTER TABLE audit_log ADD COLUMN org_id UUID NOT NULL;
ALTER TABLE audit_log ADD FOREIGN KEY(org_id) REFERENCES orgs (id);

UPDATE alembic_version SET version_num='0004_org_id_on_user_data'
  WHERE alembic_version.version_num = '0003_orgs_and_tokens';
COMMIT;
```

Live verification against the ephemeral PostgreSQL 15.17 container
on `localhost:55432` (reused from CP2/CP3 — fresh `docker run` this
session because the container was torn down between sessions). New
test file in isolation:

```
$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_server/tests/test_org_id_constraint.py \
    packages/llm_tracker_server/tests/test_storage_smoke.py \
    packages/llm_tracker_server/tests/test_org_token_models.py -q
........                                                                 [100%]
8 passed in 4.30s
```

Full suite with the test URL set (all eight PG-only smokes run; the
rest of the suite ignores the test URL):

```
$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest -q
...
257 passed, 4 warnings in 11.52s
```

Full suite without the test URL (the eight PG smokes skip; this is
the path CI and other developers will see by default):

```
$ .venv/bin/python3.12 -m pytest -q
...
249 passed, 8 skipped, 4 warnings in 7.08s
```

The 8 skips are 2 CP2 smokes + 4 CP3 smokes + 2 CP4 smokes — net
+2 on the skip total versus CP3, matching the new test file's two
cases. 249 unconditional passes is unchanged from CP3, which
confirms CP4 didn't perturb the non-PG suite. The four warnings are
the same pre-existing `DeprecationWarning: fork()` from
`cli/manage.py`, unchanged.

Ruff:

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_server
All checks passed!
$ .venv/bin/python3.12 -m ruff format --check packages/llm_tracker_server
16 files already formatted
```

No autofix passes during CP4 — the files were ruff-clean at write
time.

Defense-in-depth check (manual `psql` smoke against the live
container after the migration ran via the fixture):

- `INSERT INTO exchanges (id, session_id, started_at, provider,
  endpoint, tool_call_count, content_level) VALUES (...)` →
  `null value in column "org_id" of relation "exchanges" violates
  not-null constraint` (pinned by `test_exchange_without_org_id_rejected`).
- `INSERT INTO exchanges (..., org_id) VALUES (..., 'aaaaaaaa-...')`
  with a fabricated UUID → `insert or update on table "exchanges"
  violates foreign key constraint "exchanges_org_id_fkey"` (pinned
  by `test_exchange_with_unknown_org_id_rejected`).

Both failure paths surface as `sa.exc.IntegrityError` at the SA
layer per the test matcher; the matcher narrowing already used by
CP3 (Decisions §CP3 last bullet) carries over.

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

- **The plan is 14 checkpoints; it is not the implementation.** As
  of CP9, 9 of 14 are committed; CP10 (`min_content_level` manifest
  field + host enforcement) is the next.
- **Lifecycle audit rows are dropped under CP9.** The contextvar
  no-ops outside a request, and `audit_log.org_id` is NOT NULL
  with no service-role bypass. The call sites are still in place
  (proxy_started / proxy_stopped / plugin_loaded / etc.); a later
  checkpoint lights them up under whatever shape ADR-#2 picks
  (operator-org, system-org, separate table).
- **`AuthMiddleware` is still `BaseHTTPMiddleware`-shaped.** The
  generator-opens-fresh-session split (CP9 §D1) is the workaround;
  the long-term fix is a pure-ASGI middleware that defers
  `commit()` until after the body finishes. Flagged in CP8 §D11
  and now blocking a future CP9.5 / Phase-3c housekeeping ticket.
  Until then, every streamed request opens two sessions instead
  of one.
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

CP9 landed cleanly. Source `HEAD` is `fe18e9a`; the §5.3 finalize
commit refreshing `docs/STATUS.md` + this worklog adds one more.
The 14-checkpoint plan is **9/14 done**. The storage layer is now
org-aware end-to-end: every `Exchange` INSERT lands with
`org_id = request.state.org_id` (defense-in-depth on top of CP5's
RLS `WITH CHECK`), every audit dispatched on a request reaches
`audit_log` through a request-scoped contextvar-bound writer, and
the synthetic SSE block paths (`Block` from `on_request_received`
/ `before_forward`, `Abort` from `on_upstream_response_start`)
each persist a `blocked_by`-tagged row before returning. The
single new e2e test
(`test_two_org_e2e_isolation`) drives a real POST through the
catch-all and asserts org-A → org-B invisibility; the full server
suite is now **55 passed with PG** (39 no-PG + 16 PG-gated) and
the full repo suite without PG is **287 passed / 16 skipped**.

CP9 left two contracts CP10 will rely on:

- The transitional permissive `HookContext` from CP8 §D1 is still
  in place: `make_hook_context` returns L3 visibility for every
  plugin. CP10's job is to replace that with manifest-driven
  clamping (`min_content_level` field on `PluginManifest`).
  Existing test
  `test_begin_exchange_passes_same_ctx_to_each_hook` pins the
  current L3-visible behaviour and will need a sibling that pins
  the new clamping shape once CP10 lands.
- `PluginHost.loaded_plugins()` already serialises
  `allowed_modes` for `/admin/plugins` (ADR-0014). CP10 should
  add `min_content_level` to the same payload so the
  introspection view stays self-describing.

**Next single step**: **CP10 — `min_content_level` manifest
field + host enforcement (ADR-0019 §Open questions).** Per the
plan:

- Add `min_content_level` to the plugin manifest schema (default
  `L3`; valid values `L0` / `L1` / `L2` / `L3`).
- Server-side `PluginHost.make_hook_context` clamps each
  plugin's `HookContext` view to the declared level — a plugin
  asking for `L0` cannot reach `request_text` even when the data
  is in memory.
- Drop the mode-keyed intersection logic (already gone in CP8
  for the host, but the SDK `HookContext.request_text(level)`
  still resolves the mode-keyed ceiling internally; CP10 either
  threads `min_content_level` into the SDK or replaces the
  `mode="R"` / `user_opted_in=True` shim with the declared
  level).
- New test `tests/test_min_content_level.py`: declare a plugin
  at L1, assert it cannot access `request_text`; declare another
  at L3, assert it can.
- `/admin/plugins` payload gets `min_content_level` so manifests
  remain self-describing through introspection.

The CP9-specific contracts CP10 doesn't need to touch:

- The forwarder's storage + audit wiring stays as-is. CP10
  doesn't change INSERT shapes.
- The two-session split (middleware session pre-stream, fresh
  session post-stream) is a CP9.5 housekeeping ticket; CP10
  doesn't depend on it being resolved.

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
   `conftest.py`** once CP5's RLS test lands. CP3 copy-pasted the
   subprocess wrapper from CP2's `test_storage_smoke.py`; CP4 added
   the third copy without hoisting (see CP4 §Decisions last bullet).
   CP5's per-org seeding gives the fixture a real reason to grow,
   which is the right shape to hoist into rather than a bare copy.
   *Resolved in CP5.* `conftest.py` now owns `_run_alembic` and the
   `session_factory` fixture, and additionally wraps the
   sessionmaker so every session drops to `llm_tracker_app` via
   `SET LOCAL ROLE`. Per-org seeding stayed in
   `test_rls_two_org_isolation.py` for the reason captured in
   §Decisions §CP5.
