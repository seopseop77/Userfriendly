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
```

## What's left / known limits

- Steps 2–7 still pending (package skeleton through `fly.toml`).
- **Migration 0018 not yet applied to live Supabase.** Operator-owned per the
  standard `Supabase MCP execute_sql` in one atomic `BEGIN; ... COMMIT;`
  block matching the 0013 / 0014 / 0015 / 0016 / 0017 precedent.
- The `[GITHUB_RELEASE_URL]` placeholder in `success.html` will need a real
  URL once the `llm_tracker_agent` wheel is published to GitHub releases
  (Prompt 2 in the user's broader rollout — not in this scope).

## Handoff

**Next single step**: Step 2 — create the `packages/llm_tracker_signup/`
package skeleton (`pyproject.toml`, src layout, empty `__init__.py`) so step 4
has a place to land. Verify by `uv sync` + `python -c "import
llm_tracker_signup"`.
