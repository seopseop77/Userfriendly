# 2026-05-21 · Signup app — standalone Fly service for participant registration

**Author**: Claude Code
**Session trigger**: User instruction — build `packages/llm_tracker_signup/`,
a separate Fly app that lets research participants register and receive an API
token. The proxy server URL stays private; participants only interact with the
signup app. Multi-step task with a pre-stated plan + per-step checkpoints.
**Related docs**: `docs/design.md` §6 (framework architecture, auth flow),
ADR-0020 (per-org bearer tokens — token-issuance pattern reproduced here
without importing from `llm_tracker_server`), ADR-0033 (no-RLS posture for
operator-only tables — followed for `participant_registrations`).

## Interpretation

Brief is unusually precise (full migration SQL, package layout, route map, six
explicit tests). Two ambiguities surfaced and were resolved up front:

- **Table name typo.** The brief's CREATE TABLE block opened with
  `participant_registrations` truncated to `participaions`; the rest of the
  brief (`idx_participant_registrations_email`, `DROP TABLE
  participant_registrations`, the `DuplicateEmailError` Python contract) all
  used the long form. User confirmed: `participant_registrations` is correct.
- **ADR vs docs-only.** Considered an ADR-0034 to capture the separate-Fly-app
  decision but user judged it not hard-to-reverse enough to warrant an ADR —
  the rationale lives in this worklog's §Decisions instead.

Constraint reminder from the brief: the signup package must NOT import from
`llm_tracker_server` or `llm_tracker_agent`. Token-issuance + hashing logic is
duplicated as raw async SQL (asyncpg via SQLAlchemy `text()`) to keep the
package independent. The duplicated surface is ~10 lines (sha256 + token
generation + three INSERTs) so the cost is low; the win is the signup app can
deploy without dragging the proxy-server dependency tree.

## Plan (stated before any code)

1. Migration 0018 (`participant_registrations` table) → verify with alembic
   upgrade/downgrade `--sql` round-trip.
2. Package skeleton (pyproject.toml + directory layout + `__init__`) → verify
   with `uv sync` + `python -c "import llm_tracker_signup"`.
3. `config.py` (pydantic-settings) → verify by instantiation.
4. `registration.py` (PDF text extraction + token issuance with
   `DuplicateEmailError`) → verify with 4 unit tests.
5. `app.py` (FastAPI: `GET /healthz`, `GET /`, `POST /register`, `GET
   /success`) → verify with 2 integration tests.
6. HTML templates (`register.html`, `success.html`) → verify via the
   integration tests (form renders, success page shows token).
7. `fly.toml` for the new app → verify by file presence + key check.
8. Worklog + STATUS.md update (this file already exists, refreshed per
   checkpoint).

Each step gets its own commit and a checkpoint update to this worklog +
STATUS.md per CLAUDE.md §5.3.

## What was done

### Step 1 — Migration 0018 (commit `b35b524`)

- Created `packages/llm_tracker_server/alembic/versions/0018_participant_registrations.py`
  — `participant_registrations` table with `id UUID PK gen_random_uuid()`,
  `org_id` FK to `orgs(id)`, `token_hash` FK to `api_tokens(token_hash)`,
  `email TEXT NOT NULL UNIQUE` as the duplicate guard, `proposal_text TEXT`
  nullable (PDF upload is optional), `created_at` server-default `now()`.
  Indexed on `email` for the duplicate pre-check + operator queries.

### Step 2 — Package skeleton (commit `5f52873`)

- Created `packages/llm_tracker_signup/pyproject.toml` — FastAPI +
  uvicorn + jinja2 + python-multipart + pdfplumber + sqlalchemy[asyncio]
  + asyncpg + pydantic-settings + httpx (runtime); pytest + pytest-asyncio
  + httpx + fpdf2 (dev).
- Created `packages/llm_tracker_signup/src/llm_tracker_signup/__init__.py`
  — package docstring naming the duplication-of-token-issuance rationale
  + `__version__ = "0.0.1"`.
- Created `packages/llm_tracker_signup/src/llm_tracker_signup/templates/`
  + `packages/llm_tracker_signup/tests/` empty directories ready for
  later steps.
- Modified root `pyproject.toml` — `tool.pytest.ini_options.testpaths`
  gains `packages/llm_tracker_signup/tests`.

### Step 3 + 4 — Config + registration core (commit `070361f`)

- Created `packages/llm_tracker_signup/src/llm_tracker_signup/config.py`
  — `Settings(BaseSettings)` with `database_url` + `proxy_server_url`,
  `env_prefix="LLMTRACK_"`. No `Literal` typing on the URL fields — they
  are operator-provided strings, validated only at engine-create time.
- Created `packages/llm_tracker_signup/src/llm_tracker_signup/registration.py`
  — `extract_pdf_text(pdf_bytes: bytes) -> str` (pdfplumber over a
  BytesIO buffer; returns `""` on parse failure or empty input);
  `DuplicateEmailError` carrying the email it raised on;
  `register_participant(engine, *, name, email, institution,
  research_description, proposal_text) -> str` — three INSERTs in one
  `engine.begin()` transaction (orgs, api_tokens,
  participant_registrations) after a SELECT-by-email duplicate
  pre-check. Token shape is `"lts_" + secrets.token_urlsafe(32)`
  (SHA-256 hex stored, plaintext returned once).
- Created `packages/llm_tracker_signup/tests/conftest.py` — `db_engine`
  fixture that skips when `LLMTRACK_TEST_DATABASE_URL` is unset; when
  set, runs alembic upgrade/downgrade via subprocess against the proxy
  server's `alembic.ini` (subprocess invocation, NOT a Python import
  from `llm_tracker_server`).
- Created `packages/llm_tracker_signup/tests/test_registration.py` —
  five tests: 3 PDF unit tests (happy / bad bytes / empty bytes), 2
  DB-gated tests (happy token issuance, duplicate email raises). PDF
  tests use `fpdf2` to construct minimal valid PDF bytes at runtime
  rather than checking in a binary fixture.

### Step 5 + 6 — FastAPI app + HTML templates (commit `ab2924f`)

- Created `packages/llm_tracker_signup/src/llm_tracker_signup/app.py`
  — `create_app(settings, engine)` factory wires four routes:
  `GET /healthz` for Fly health checks, `GET /` rendering the form
  template, `POST /register` accepting multipart form fields +
  optional `UploadFile` PDF (extracted in-process, never persisted to
  disk; on `DuplicateEmailError` re-renders the form with the user's
  input + a 400 status), `GET /success` rendering the token + install
  steps. Single `AsyncEngine` owned by lifespan; tests inject an
  external engine.
- Created `packages/llm_tracker_signup/src/llm_tracker_signup/templates/register.html`
  — Tailwind CDN, five form fields (`name`, `email`, `institution`,
  `research_description` textarea, `proposal` `accept=".pdf"` file),
  submit button with loading state + spinner, inline JS for the PDF-
  extension check.
- Created `packages/llm_tracker_signup/src/llm_tracker_signup/templates/success.html`
  — Tailwind CDN, amber warning banner ("This token will not be
  shown again"), monospace token box with a copy-to-clipboard button
  using `navigator.clipboard.writeText` + visual "Copied!" feedback,
  three install-step cards (`pip install [GITHUB_RELEASE_URL]`,
  `claude-manage setup {{ token }} [--server-url …]`, `claude-manage`).
- Created `packages/llm_tracker_signup/tests/test_app.py` — six route
  tests via httpx `AsyncClient` + `ASGITransport`: GET / renders the
  form, GET /healthz returns `{"status": "ok"}`, GET /success embeds
  the token + the placeholder + the proxy URL, POST /register with
  PDF upload returns 303 to `/success?token=lts_…`, POST /register
  without PDF also succeeds, POST /register with a re-used email
  returns 400 with `"already registered"` in the body. The three
  POST-`/register` tests use the `db_engine` fixture (skipped without
  a test DB).

### Step 7 — fly.toml (commit `a77358b`)

- Created `packages/llm_tracker_signup/fly.toml` — `app =
  "llm-tracker-signup"`, `primary_region = "nrt"`, `[http_service]`
  block with `internal_port = 8000`, `force_https = true`,
  `auto_stop_machines = "stop"`, `auto_start_machines = true`,
  `min_machines_running = 0`, `PORT = "8000"` in `[env]`. Required
  secrets (`LLMTRACK_DATABASE_URL`, `LLMTRACK_PROXY_SERVER_URL`)
  documented in the file header but never inlined. No Dockerfile yet
  — Fly's buildpack auto-detection handles the FastAPI app.

## Decisions

- **No ADR for the separate-Fly-app architecture.** User judged the decision
  not hard-to-reverse — a future merge of signup-app into the proxy server is
  not blocked by this choice. The rationale (private proxy URL, independent
  deploy cadence, no proxy-server dependency tree on signup boot) lives here
  instead.
- **`email UNIQUE` at the column, not a deferred constraint.** Brief
  explicitly says `email TEXT NOT NULL UNIQUE` — column-level UNIQUE creates
  both the constraint AND a backing index. The brief's separately-requested
  `idx_participant_registrations_email` is added on top so operator `WHERE
  email = …` queries can use either; PostgreSQL's planner is fine with the
  redundancy (the second index is a no-op against the duplicate-check path
  but keeps query-shape stability if the constraint is ever named differently
  in a future migration).
- **No RLS on `participant_registrations`.** Same posture as
  `plugin_analytics` (ADR-0033) — the signup app uses its own `AsyncEngine`
  from a separate Fly service, so the GUC binding pattern the proxy server's
  `AuthMiddleware` issues does not apply. Adding RLS would require the
  signup app to issue `SET LOCAL app.org_id = …` for a table no end-user
  surface reads.
- **No GRANT to `llm_tracker_app`.** That role exists for the proxy server's
  per-request session binding. The signup app connects with its own role
  (whatever `LLMTRACK_DATABASE_URL` resolves to on the new Fly app — likely
  the Supabase admin/owner role used by alembic). Adding a GRANT here would
  imply the proxy server itself writes to `participant_registrations`, which
  it does not.
- **PDF text-extraction returns empty string on failure, not raises.** A
  malformed upload should not block registration: the operator still has the
  required `research_description` textarea contents, and the participant
  shouldn't be locked out for an unrelated PDF-parser quirk. Image-only PDFs
  (which legitimately have no text layer) take the same path. The store-or-
  discard branch in `app.py` keeps the column NULL when the extracted text
  is empty so it cleanly distinguishes "no PDF uploaded" from "PDF with
  text" downstream.
- **Token issuance duplicates `llm_tracker_server.auth.tokens.issue`,
  doesn't import it.** Constraint from the brief, and the right call: the
  signup app's deploy unit is independent of the proxy server's package
  tree, and the duplicated surface (~10 lines: sha256 + token_urlsafe +
  three INSERTs) is small enough that drift is unlikely. If the proxy
  server's token shape ever evolves (e.g. a different prefix), both call
  sites need updating in lockstep — same risk a single shared module would
  carry against a future plugin-style refactor.
- **Duplicate-email path re-renders the form, not a JSON 400.** Brief said
  "400 with error message"; both shapes satisfy that, but a browser-facing
  signup app benefits from preserving the user's filled-in fields. The
  re-render still returns 400 (test pinned) so any future programmatic
  client also sees the correct status.
- **`@Annotated[…, Form()]` instead of `= Form(...)`.** Modern FastAPI
  signature style; ruff's `B008` flags function calls in argument
  defaults. Same outcome (FastAPI parses the form), cleaner shape, no
  per-line `noqa`.
- **`templates.TemplateResponse(request, "name.html", {...})` request-
  first signature.** The older `(name, {"request": request, ...})` form
  is deprecated in current Starlette and breaks against Jinja2's LRU
  cache (the context dict gets cached by identity, which fails with
  `unhashable type: 'dict'`). Caught by the first integration-test run
  and migrated to the request-first signature across all three
  `TemplateResponse` sites.
- **Tests gate on `LLMTRACK_TEST_DATABASE_URL`, not a Postgres
  container fixture.** Matches the proxy-server conftest convention so
  the same env knob unblocks both packages' DB tests on CI. Pure-
  function tests (PDF extraction, template rendering, healthz) always
  run; the five DB-touching tests skip cleanly when the env var is
  unset — the route-rendering coverage stays meaningful without a DB.

## Verification

```
$ cd packages/llm_tracker_server && ../../.venv/bin/python3.12 -m alembic \
    upgrade --sql 0017_drop_exchanges_session_id:0018_participant_registrations
# Clean BEGIN ... COMMIT:
#   CREATE TABLE participant_registrations (...);
#   CREATE INDEX idx_participant_registrations_email ON ... (email);
#   UPDATE alembic_version SET version_num='0018_participant_registrations';

$ ../../.venv/bin/python3.12 -m alembic downgrade \
    --sql 0018_participant_registrations:0017_drop_exchanges_session_id
# Clean reverse:
#   DROP INDEX idx_participant_registrations_email;
#   DROP TABLE participant_registrations;

$ uv sync   # picks up packages/llm_tracker_signup as a workspace member
$ .venv/bin/python3.12 -c "import llm_tracker_signup; print(llm_tracker_signup.__version__)"
0.0.1

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_signup/tests/ -v
... 6 passed, 5 skipped in 0.63s
# 3 PDF unit tests + 3 template/healthz route tests pass; the 5
# DB-gated tests skip cleanly without LLMTRACK_TEST_DATABASE_URL.

$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_signup/
All checks passed!

$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_sdk \
    packages/llm_tracker_plugin_analytics_sink \
    packages/llm_tracker_server \
    packages/llm_tracker_signup -q
168 passed, 23 skipped in 6.23s
```

Test-count delta vs the prior session baseline (162 passed + 18
skipped at the start of this track):

* +6 newly passing (3 PDF extraction + 3 template/route rendering).
* +5 newly skipping (2 token-issuance + 3 register-route — all gated
  on `LLMTRACK_TEST_DATABASE_URL`).
* Zero regressions in the proxy server / SDK / analytics_sink
  packages.

## What's left / known limits

- **Migration 0018 not yet applied to live Supabase.** Operator-owned
  per the standard `Supabase MCP execute_sql` in one atomic `BEGIN;
  ... COMMIT;` block matching the 0013 / 0014 / 0015 / 0016 / 0017
  precedent. Without live apply, the new Fly app's first registration
  will `UndefinedTable`-fail.
- **First-time `fly deploy` of `llm-tracker-signup` is operator-
  owned.** This is a brand-new Fly app that needs `fly apps create`,
  the two required secrets (`LLMTRACK_DATABASE_URL`,
  `LLMTRACK_PROXY_SERVER_URL`), and a first deploy. No Dockerfile yet
  — Fly's Python buildpack detection covers the FastAPI app shape.
- **The `[GITHUB_RELEASE_URL]` placeholder** in `success.html` needs
  the real URL once the `llm_tracker_agent` wheel is published to
  GitHub releases (Prompt 2 in the user's broader rollout — not in
  this scope).
- **DB-gated tests stay skipped locally** until
  `LLMTRACK_TEST_DATABASE_URL` is set against a throwaway Postgres.
  The proxy-server tests behind the same gate are similarly skipped
  by default; same convention.
- **Empty PDF text + non-PDF upload** are both treated as "no
  proposal_text" (NULL in DB). If a future flow needs to distinguish
  "parser failed" from "PDF had no text", `extract_pdf_text` would
  need to grow a richer return shape (e.g. `tuple[str, bool]`).

## Handoff

**Track is code-complete** through Steps 1–7 plus this docs
checkpoint (Step 8). Operator-owned next steps in order:

1. Apply migration 0018 to Supabase via MCP `execute_sql` in one
   atomic `BEGIN; ... COMMIT;` block. Pre-state should show alembic
   at `0017_drop_exchanges_session_id` and no `participant_registrations`
   table; post-state should show alembic at
   `0018_participant_registrations`, the table present, and the
   `email` btree index.
2. Provision the new Fly app — `fly apps create llm-tracker-signup`,
   then `fly secrets set LLMTRACK_DATABASE_URL=… LLMTRACK_PROXY_SERVER_URL=…`,
   then `fly deploy -c packages/llm_tracker_signup/fly.toml`.
3. Smoke: open the deployed URL, submit a test registration, verify
   the redirect lands at `/success?token=lts_…`, and that the row
   appears in `participant_registrations`.

The `[GITHUB_RELEASE_URL]` placeholder is a separate follow-up (after
the agent wheel is published).
