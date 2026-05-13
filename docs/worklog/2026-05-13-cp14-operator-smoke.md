# 2026-05-13 · Phase 3c CP14 — operator-only end-to-end smoke (closed)

**Author**: Claude Code
**Session trigger**: "현재 deployed된 상태에서 내가 OAuth claude code를
이용해서 프록시 서버에 전송이 되는지를 테스트할 수 있는 상태야?" → pivoted
to STATUS.md's prescribed CP14 (operator-only curl smoke) once the OAuth
Claude Code path turned out to need a separate header-injection layer
that is not yet built (Phase 3b deferred).
**Related docs**: ADR-0017 (server pivot), ADR-0018 (per-org RLS),
ADR-0020 (auth model), ADR-0023 (header rename),
`docs/worklog/2026-05-11-phase3c-plan.md` (CP plan-of-record),
`docs/worklog/2026-05-13-auth-header-rename.md` (immediate predecessor),
`docs/worklog/2026-05-13-cp13b-fly-deploy.md` (the deploy that landed
the live server).

## Interpretation

The user's literal question was whether OAuth Claude Code itself could
already talk to the deployed proxy. Two findings narrowed scope:

1. `https://llm-tracker-server.fly.dev/v1/messages` (no auth) returned
   `HTTP 401 {"detail":"missing X-LLM-Tracker-Token header"}` — i.e.
   ADR-0023's renamed header is *already* live (STATUS.md's "needs a
   redeploy first" note was stale; the rename build had already shipped).
2. Claude Code itself has no surface for injecting an arbitrary
   `X-LLM-Tracker-Token` header onto its outbound requests. Phase 3b's
   thin local agent (deferred per Phase-3a queue items #1/#4) is the
   intended carrier. Without it, OAuth-Claude-Code-to-server is not
   directly testable end-to-end yet.

→ The actionable subset of the user's question maps cleanly to
STATUS.md's "Next single step": **Phase 3c CP14 — operator-only smoke
via curl**. Treated the OAuth-Claude-Code half as a Phase 3b carry-over
and proceeded with CP14.

## What was done

- Probed the live server: `/healthz` → 200; `POST /v1/messages` no auth
  → 401 with the post-ADR-0023 message body, confirming the rename build
  is already in production.
- Issued the demo per-org bearer token:
  `fly ssh console -a llm-tracker-server -C "llm-tracker-server tokens
  issue --org demo"` — output included `org_id=
  c6fcdd23-1313-48e7-8c99-d6e7577a4b08`, `token_hash=60245689...`, plus
  the one-time plaintext (delivered to operator, not committed).
  `tokens issue` auto-created the `demo` org row; no separate
  `orgs create` was needed.
- First real curl (operator-run with valid Anthropic `x-api-key` and the
  demo `X-LLM-Tracker-Token`) returned **`HTTP 500 Internal Server
  Error`**. fly logs revealed:

  ```
  asyncpg.exceptions.InsufficientPrivilegeError:
      permission denied to set role "llm_tracker_app"
  [SQL: SET LOCAL ROLE llm_tracker_app]
  File ".../llm_tracker_server/auth/middleware.py", line 83
  ```

- Diagnosed via Supabase MCP `execute_sql` on `pg_auth_members`:
  `postgres` was *already* a member of `llm_tracker_app` (Supabase
  auto-grants `postgres` membership of newly created roles), but with
  `admin_option=true, inherit_option=false, set_option=false`. PG16
  split role membership into three orthogonal options; the
  pre-PG16 coupling of "membership implies SET ROLE" no longer holds,
  so `SET LOCAL ROLE` failed despite the membership being present.
- Applied the immediate unblock via Supabase MCP:
  `GRANT llm_tracker_app TO postgres WITH SET TRUE` — created a second
  `pg_auth_members` row with `set_option=true, inherit_option=true,
  admin_option=false` (Postgres ORs option rows together → effective:
  all three true).
- Verified the unblock with an invalid-token probe (no Anthropic key
  needed): same `/v1/messages` endpoint with a garbage
  `X-LLM-Tracker-Token` → **`HTTP 403 {"detail":"unknown or revoked
  token"}`** (was: 500). Confirms `SET LOCAL ROLE` now passes and
  `lookup()` runs.
- Operator re-ran the real curl → **`HTTP 200`**. fly logs:

  ```
  05:09:16 proxy.forward POST v1/messages (forwarded_credential: true)
  05:09:22 HTTP Request: POST https://api.anthropic.com/v1/messages
           "HTTP/1.1 200 OK"
  05:09:22 POST /v1/messages HTTP/1.1" 200 OK
  ```

  No traceback in the request window.
- Verified `public.exchanges` via Supabase MCP — one row scoped to the
  demo org:

  ```
  id=01KRFVTG1E7Q72QN7E5MP26JXY
  session_id=server
  org_id=c6fcdd23-1313-48e7-8c99-d6e7577a4b08   (org_name="demo")
  started_at_ts=2026-05-13 05:09:16.974+00
  endpoint=v1/messages   provider=anthropic
  content_level=L3
  ```

  (Plus a sibling row at 04:11:39.905+00 from the earlier 400-BadRequest
  debug curl, also scoped to demo — confirms multi-tenancy isolation
  fires on the first request, regardless of upstream outcome.)
- Created `packages/llm_tracker_server/alembic/versions/0006_grant_app_role_set_membership.py`
  (commit `458a4ba`): bakes the GRANT into the build pipeline,
  emitting `GRANT llm_tracker_app TO CURRENT_USER WITH SET TRUE` on
  PG16+ and the plain `GRANT llm_tracker_app TO CURRENT_USER` on
  PG15 (the local docker test fixture). 61/61 server tests green;
  ruff clean.

## Decisions

- **Used Supabase MCP `execute_sql` for the immediate unblock instead of
  writing the migration first.** Reason: the 500 was blocking CP14
  end-to-end; the manual GRANT is byte-identical-effect to the eventual
  migration's emit and is fully idempotent. Writing + testing +
  deploying the migration first would have been a 1+ hour loop; the
  manual MCP run was 5 minutes. The migration (`458a4ba`) is the durable
  fix; the MCP run was the production-side equivalent of `alembic
  stamp` on a hot fix.
- **Migration 0006 branches on server version via a DO-block.** Reason:
  the local docker test fixture is `postgres:15` (the `cp2` superuser
  image in CLAUDE.md §12). PG15 rejects `WITH SET TRUE` as a syntax
  error — its `GRANT role TO user` form pre-dates the PG16 split, and
  on PG15 membership unconditionally implies SET ROLE. The alternatives
  considered:
  - Upgrade the test fixture to PG16+ — broader-scope change touching
    `docker run` recipes and the test smoke commands.
  - Drop the GRANT in the migration entirely and rely on
    operator-side `GRANT` in Supabase dashboard — reintroduces the
    exact deploy gap CP14 just surfaced.
  - Conditional `EXECUTE` in DO block — contained to migration 0006,
    zero side effects on the test path.
  Picked the third.
- **Did not redeploy immediately.** The GRANT is already in place on
  Supabase from the MCP run; the live server's behavior already matches
  the migration's effect. Letting the next legitimate code change carry
  the deploy keeps deploys-vs-commits aligned. Trade-off: alembic state
  on Supabase shows `0005_rls_policies` head while the migration code
  says head is `0006_grant_app_role_set`. Operator can `fly ssh console
  -C "alembic stamp 0006_grant_app_role_set"` to sync without deploy,
  or wait for the next deploy (migration is idempotent → no-op).
- **Did not investigate the response-side NULL columns in this
  checkpoint.** Per user's Option B selection: deferred to a separate
  track. The row landed (CP14's pass criterion); the row is
  *underpopulated*, which is a Phase 3c carry-over rather than a
  CP14 failure. See "What's left".

## Verification

```
$ curl -i https://llm-tracker-server.fly.dev/healthz
HTTP/2 200 ...
{"status":"ok","version":"0.0.1"}

$ curl -i -X POST https://llm-tracker-server.fly.dev/v1/messages \
    -H "Content-Type: application/json" \
    -H "X-LLM-Tracker-Token: <demo>" \
    -d '{...}'
... pre-fix:  HTTP 500 (asyncpg permission denied to set role)
... post-fix-with-bad-token:  HTTP 403 {"detail":"unknown or revoked token"}
... post-fix-with-good-token + Anthropic key:  HTTP 200 (operator-run)

$ # fly logs --since 5m
... proxy.forward (forwarded_credential: true)
... HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
... INFO: "POST /v1/messages HTTP/1.1" 200 OK
(no traceback)

$ # Supabase MCP: SELECT ... FROM exchanges ORDER BY started_at DESC LIMIT 5
[1 row scoped to demo org at 05:09:16Z post-fix-with-good-token,
 1 row scoped to demo org at 04:11:39Z from the earlier 400-BadRequest debug]

$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker_server/alembic/versions/0006_grant_app_role_set_membership.py
All checks passed!

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
61 passed in 25.70s
```

## What's left / known limits

- **Response-side metadata NULL on the CP14 exchange row.** The
  successful 200-OK row has `started_at`, `endpoint`, `provider`,
  `content_level`, `org_id` populated, but `ended_at`,
  `model_requested`, `model_served`, `status_code`, `input_tokens`,
  `output_tokens`, `latency_ms`, `stop_reason` are all NULL. The
  request-open INSERT works; the stream-close UPDATE that should fill
  the response-side fields is silent on a 200-OK SSE response. STATUS
  CP9's closed-checkpoint note flagged `model_served=null` only for
  HTTP-error (non-SSE) responses as a by-design observability hole —
  the current finding extends that hole into the happy SSE path and
  needs a separate investigation. Suspect: CP8's server-side plugin
  host port either lost the `on_persisted` hook trigger or the
  follow-up UPDATE is failing silently. Owner: server's exchange
  persistence layer + plugin host hook dispatch.
- **alembic state drift between code and live DB.** Live Supabase
  `alembic_version` is `0005_rls_policies`; migration head in code is
  `0006_grant_app_role_set`. Next `fly deploy` will resolve via
  `alembic upgrade head` (no-op due to idempotency). Operator can
  also stamp now: `fly ssh console -a llm-tracker-server -C
  "alembic stamp 0006_grant_app_role_set"`.
- **PG16-specific deploy-time validation has no local test signal.**
  All 61 tests run against PG15, where `SET ROLE` works without explicit
  SET-option-grant. The CP14-style failure mode is invisible to the
  local fixture. Long-term: either dockerize tests against PG16+
  (matching Supabase), or add an integration test that asserts
  `pg_auth_members.set_option = true` after running migrations as a
  non-superuser. Not in scope for this checkpoint.
- **Cosmetic: two `pg_auth_members` rows for `(postgres,
  llm_tracker_app)` on Supabase.** Result of Supabase's auto-grant +
  our manual GRANT not being merged by Postgres. Permissions are the
  OR of all rows (effective: admin+inherit+set), so behavior is
  unchanged. A single canonical row could be restored with REVOKE +
  GRANT but is not load-bearing.

## Handoff

Phase 3c CP14 is **closed**. With this, Phase 3c is 14/14
plan-checkpoints done — Phase 3c overall flips to "closed (operator
smoke validated)". The natural next checkpoints are:

1. **Investigate response-side NULL columns** (highest signal; reuses
   the live demo org and token). Spin up a fresh worklog
   `2026-05-13-cp14-response-side-followup.md` (or a Phase-3d/CP15
   slug) and start with: read the on_persisted hook dispatch path in
   the server's plugin host port (CP8 area) + the exchange UPDATE
   statement in `storage` (CP9 area), check whether the close-out
   path runs at all on a 200-OK SSE, then either fix or surface
   as an ADR.
2. **Stamp 0006 on live Supabase** to align alembic state (or wait for
   next deploy).
3. **ADR-#2 consent + data-handling** remains blocking *any external
   testing* and should run alongside Phase-3c carry-over work.

The OAuth Claude Code question that started this session is **not**
yet answerable in the affirmative — it remains gated on Phase 3b
(thin local agent or equivalent header-injection sidecar). Phase 3b
itself is gated on ADR-#1 (fallback) and ADR-#4 (agent language).

## Suggestions (untouched)

- The CP9 close-out note already flagged `model_served=null` for
  HTTP-error bodies as a by-design observability hole. The CP14
  finding extends the same gap into 200-OK SSE. Worth folding both
  into a single ADR on "exchange row close-out policy" rather than
  patching ad hoc — the same code path determines both behaviors.
- The `pg_auth_members.set_option` quirk could trip future ops on
  any PG16+ managed Postgres (RDS, Cloud SQL, Neon, ...), not just
  Supabase. Worth a paragraph in `docs/deploy.md` next to the
  existing pgbouncer/asyncpg note.
