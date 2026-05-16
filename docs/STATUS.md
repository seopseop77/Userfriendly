# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-17 (Claude Code; **ADR-0029 consent + data-handling — Accepted; HookContext-level scrubber landed.** Six-axis policy: full L3 storage, docs-only disclosure, 6-month retention, operator-handled deletion, `sk-`/`lts_`/`Bearer <value>`/email scrubbing at the SDK accessor surface (`request_text` + `response_content_json` pipe through `llm_tracker_sdk.scrubbers.scrub`; raw `_raw_request_body` + `_parsed_response` left untouched so storage stays canonical per ADR-0028). New module `packages/llm_tracker_sdk/src/llm_tracker_sdk/scrubbers.py` + 16 scrubber unit tests + 4 accessor-level wiring tests. `docs/deploy.md` gains a "Data collection & privacy" section; `docs/plugins.md` gains §3.2 documenting the storage-vs-accessor asymmetry. Full repo test suite 354 passed under DB fixture (+20 new), 338 passed no-DB. External (non-team) testing of the central server is no longer blocked on consent + data-handling policy — operator deploying the new image is the operational next step before external traffic.)
**Updated by**: Claude Code (ADR-0029 + accessor-level scrubber)

## Current phase

- **Phase**: **Phase 3b — CLOSED (2026-05-13).** Thin local agent
  `claude-manage` (`packages/llm_tracker_agent/`) shipped over
  three commits (`79a0ae9` ADRs / `fbd36e4` agent code /
  `ac4370c` multi-instance fallback) and live-verified by the
  user against `https://llm-tracker-server.fly.dev`. Surface area
  in production:
  - `claude-manage setup <token> [--server-url ...] [--port ...]`
    writes `~/.llm-tracker/config.toml` (`0o600`).
  - `claude-manage` (default) picks a free loopback port —
    preferred from config, else kernel-assigned ephemeral so
    multiple instances coexist — runs the FastAPI proxy that
    injects `X-LLM-Tracker-Token` + strips hop-by-hop, polls
    `/healthz` for ≤ 3s readiness, sets `ANTHROPIC_BASE_URL`, and
    spawns `claude <extra-args>`.
  - Fail-closed per ADR-0024 confirmed end-to-end in negative
    smoke: 503 propagates to Anthropic SDK → 10 retries with
    backoff → user-facing failure, no Anthropic bypass.
- **Active task**: **Draft ADR-0026 — "exchange row close-out
  policy"** (formerly slotted as "ADR-0024", renumbered after
  today's agent fail-closed ADR took 0024). Decides three things:
  (1) which `public.exchanges` columns are guaranteed-populated
  vs. allowed-NULL and on which paths; (2) error path — today
  there is no INSERT at all if upstream fails pre-SSE; (3)
  blocked-path field parity with the streaming path. Drafting
  before Option B so its `record_exchange_timing` signature
  extension lands under a stable contract.
- **Other follow-ups** (queued):
  - **Phase-3c follow-up Option B — SSE extractor** for the five
    response-side fields still NULL on exchange rows
    (`model_served`, `input_tokens`, `output_tokens`, `cache_*`,
    `stop_reason`). Gated on ADR-0026 acceptance. Bonus side
    benefit: makes the latency-vs-output_tokens analysis
    flagged in today's smoke side-investigation tractable.
  - ~~**ADR-#2 consent + data-handling**~~ **Closed 2026-05-17**
    by ADR-0029. External (non-team) testing no longer blocked on
    policy; operator-deploy of `a4c08b3` is the operational next
    step.

## Active worklog

`docs/worklog/2026-05-17-adr-0029-consent.md` — ADR-0029 (Accepted)
records the six-axis policy; code commit `a4c08b3` lands the SDK
scrubber + HookContext wiring + deploy/plugins disclosure paragraphs.
Operator-deploy of the new image is the operational next step (no
plugin-side edits needed — `analytics_sink` already imports the SDK
that picks up the scrubber). Prior session worklogs preserved:
`docs/worklog/2026-05-16-extractor-faithful-response.md` (ADR-0028 +
operator smoke closure),
`docs/worklog/2026-05-14-plugin-ecosystem.md` (Option B SSE
extractor + analytics_sink + keyword_block multi-checkpoint
session; ADR-0026 + ADR-0027 land in checkpoint α),
`docs/worklog/2026-05-13-phase3b-agent.md` (Phase 3b — ADRs
0024 / 0025 + `packages/llm_tracker_agent/` shipped),
`docs/worklog/2026-05-13-cp14-response-side-followup.md` (CP14
response-side investigation — now Option B execution), and
`docs/worklog/2026-05-13-cp14-operator-smoke.md` (closes Phase 3c
CP14 proper).

## Recent commits

```
a4c08b3   sdk: HookContext scrubbing + ADR-0029 (consent)
140b5d4   chore: add pptx file to .gitignore
3162864   docs: STATUS + worklog — operator smoke closure
8cd9566   infra: enable keyword_block on Fly (live config)
c95e60c   docs: STATUS + worklog — ADR-0028 extractor faithful reassembly
```

## Where we paused

**ADR-0029 — consent + data-handling — Accepted (2026-05-17).** The
six-axis decision packet the user supplied lands as policy + code in
one commit (`a4c08b3`):

- **Axis 1** — full L3 storage; `LLMTRACK_PLUGINS_DISABLED` stays the
  operator off-switch for `analytics_sink`.
- **Axis 2** — documentation-only disclosure (`docs/deploy.md` new
  "Data collection & privacy" section; `docs/plugins.md` §3.2). No
  per-task consent UI.
- **Axis 3** — 6-month retention policy stated; automated deletion
  deferred.
- **Axis 4** — operator-handled SQL deletion on `org_id` / `session_id`;
  typed endpoint deferred until `session_id` is real (currently
  hardcoded `"server"`).
- **Axis 5** — `sk-`/`lts_`/`Bearer <value>`/email regex redaction with
  kind-tagged replacements (`[REDACTED:secret|token|bearer|email]`).
  Privacy-tilted: `\bsk-` over-redacts after `-` (documented + pinned
  by test).
- **Axis 6** — scrubbing at the SDK accessor (`HookContext.request_text`,
  `HookContext.response_content_json`); raw `_raw_request_body` and
  `_parsed_response` left untouched so storage stays canonical per
  ADR-0028.

The pre-existing structlog log-side scrubber
(`llm_tracker_server.proxy.credential`) stays as defence-in-depth for
log event dicts; ADR-0029 explicitly does not unify the two layers
today.

Test deltas (verified with and without the DB fixture):

```
no-DB:  338 passed, 16 skipped, 4 warnings in 13.05s   (was 318 / +20)
DB:     354 passed, 4 warnings in 30.88s               (was 334 / +20)
```

The +20 splits into 16 new scrubber unit tests
(`packages/llm_tracker/tests/test_scrubbers.py`) + 4 new accessor-level
wiring tests in `packages/llm_tracker/tests/test_hook_context.py`.

Smoke from the 2026-05-16 closure remains the latest production
state — the central server is still on commit `8138d91` until the
operator runs `fly deploy` to pick up `a4c08b3`. No code-side
operator-smoke is owed for this CP because the scrubber is in the SDK
that `analytics_sink` already imports; the next routine deploy lands
it without plugin-side changes.

The verbatim `response_json` shape from production:

```json
{
  "model": "claude-opus-4-7",
  "content": [
    {"type": "thinking", "thinking": "", "signature": "EoEC..."},
    {"type": "tool_use",
     "id": "toolu_01HgwgDtcBKBChGSpUBQeLoj",
     "name": "Bash",
     "input": {"command": "date \"+%Y-%m-%d %H:%M:%S %Z\"",
               "description": "Print current date and time"}}
  ],
  "stop_reason": "tool_use",
  "usage": {"input_tokens": 6, "output_tokens": 152,
            "cache_read_input_tokens": 75512,
            "cache_creation_input_tokens": 133}
}
```

What this row independently proves:

- **ADR-0028 faithful reassembly is live.** `content` carries both
  the thinking block (with `signature_delta` preserved despite an
  empty `thinking_delta` stream) and the tool_use block, whose
  `input` is a *parsed dict* — `_finalize_input_json` parsed the
  `input_json_delta` buffer cleanly, no `_input_json_raw` fallback.
  Pre-`8138d91` this row would have been `content: []`.
- **Option B (2026-05-14) is live on the same image.** All five
  SSE-derived columns are populated: `model_served`, `input_tokens`,
  `output_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens`, and `stop_reason`. The 2026-05-14
  worklog's four-step recipe (deploy → `/admin/plugins` → real
  request → Supabase MCP check) is end-to-end satisfied.

`keyword_block` also exercised in production: operator set
`LLMTRACK_KEYWORD_BLOCK_LIST = "no_response"` in `fly.toml` (was the
empty default), redeployed, and confirmed the operator-configurable
block path. Kept as the live operator config post-smoke — see the
`infra:` commit in "Recent commits" below.

Both workstreams are **production-validated as of this CP**. Smoke
gate closed.

Auxiliary CP carry-overs (unchanged from 2026-05-16 worklog):

- **`exchanges.tool_call_count` stays at 0 placeholder.** Derive
  from `response_json.content` via `jsonb_path_query` at analysis
  time; column's fate (deprecate / drop / leave) queued.
- **Backfill posture**: pre-`8138d91` `plugin_analytics` rows
  under a tool_use `stop_reason` carry `content: []` irrecoverably.
  Operator queries on historical rows must filter
  `WHERE created_at >= <deploy_time_of_8138d91>`.

---

### Prior workstream — Phase 3b (closed 2026-05-13)

**Phase 3b — CLOSED (live smoke verified by user).** Three commits
in that session built the agent:

1. `c124458` — pre-step tightening of `CLAUDE.md` (central-server
   stack/structure correction; token trim). Not Phase 3b proper.
2. `79a0ae9` — ADR-0024 (agent fail-closed) + ADR-0025 (Python CLI
   distribution). Both Accepted. Settle Phase-3a items #1 and #4.
3. `fbd36e4` — agent package. Net +511 lines: `pyproject.toml` +
   `__init__.py` + `config.py` + `proxy.py` + `cli.py` + 4 config
   tests + 3 proxy tests + 1 line in root `pyproject.toml`
   testpaths + uv.lock churn.

Verification recap (full output in
`docs/worklog/2026-05-13-phase3b-agent.md` §Verification):

```
$ uv run ruff check packages/llm_tracker_agent
All checks passed!
$ uv run pytest packages/llm_tracker_agent/tests/ -v
7 passed in 0.12s
$ uv run pytest -q
300 passed, 16 skipped, 4 warnings in 12.40s
$ uv run claude-manage setup lts_test_token \
      --server-url http://localhost:18080 --port 18080
Saved /Users/minseop/.llm-tracker/config.toml. Run `claude-manage` to start.
$ ls -la ~/.llm-tracker/config.toml
-rw-------@ 1 minseop  staff  84 May 13 17:19 ...
```

`-rw-------` confirms the 0o600 chmod fired. The test token
(`lts_test_token`) left in the file is junk — the external smoke
tester needs to re-run `claude-manage setup <real-token>` before
launching Claude Code through the proxy in earnest.

**Spec deviations** (recorded for the next reader):

- Spec asked for `os.execvp("claude", ...)`; implementation uses
  `subprocess.run(["claude", ...])` because `os.execvp` replaces
  the Python process image and kills the in-thread uvicorn proxy
  before Claude's first request hits it. Inline comment in
  `cli.py._run` explains; the worklog §Decisions captures the
  reasoning.
- Proxy uses `aiter_bytes()` not `aiter_raw()` because
  `httpx.MockTransport(content=b"...")` returns a response with an
  already-consumed stream, breaking `aiter_raw()` in tests.
  `aiter_bytes()` has an explicit fast-path for buffered content
  and is production-equivalent on SSE (no gzip). Response-side
  `Content-Encoding` is therefore stripped to keep the downstream
  client from double-decoding.

**Follow-up after the main checkpoint** (commit `ac4370c`):
`_pick_port` helper added so two `claude-manage` instances no
longer collide on the preferred port. The first claims
`config.local_port`; subsequent instances fall back to a
kernel-assigned ephemeral port and announce on stderr. Each
instance owns its own proxy; killing one no longer breaks the
others. Two unit tests added; full suite now 302 passed / 16
skipped. Worklog §"Follow-up — multi-instance via ephemeral port"
captures the race-window note.

**Closure — live smoke verified by user** (later in this session):

- **Positive**: `claude-manage` → live Fly.io server →
  Anthropic → back. 8 new timed rows in `public.exchanges`
  scoped to demo `org_id=c6fcdd23-...` covering opus-4-7 (5),
  opus-4-5 (1, CP14 baseline), haiku-4-5 (3). `latency_ms`
  range: haiku 913–3568 ms, opus 1820–12010 ms. Sub-second
  haiku is direct evidence that server-side overhead (auth +
  RLS + plugin host + INSERT) is in the tens of ms; the rest
  is Anthropic generation time.
- **Negative**: pointed `--server-url` at `http://127.0.0.1:9`
  (discard port). `claude-manage` returned 503 with body
  `{"detail": "llm-tracker central server unreachable"}`; the
  in-process Anthropic SDK retried 10× before surfacing the
  failure. Request never reached Anthropic — ADR-0024
  fail-closed contract held end-to-end.
- **Latency outlier note** (not blocking): the 12010 ms
  opus-4-7 row stands out; full diagnosis is gated on Option B
  SSE extractor populating `output_tokens` so we can compute
  ms/token and identify whether it was a long response or a
  cold-path call. Flagged for Option B work.

Phase 3b is now in production use. New team members install via
`uv sync` (workspace) or
`pip install "git+<repo>.git#subdirectory=packages/llm_tracker_agent"`
(standalone), then `claude-manage setup <token> && claude-manage`.

---

### Prior workstream — Phase 3c CP14 follow-up Option A (closed 2026-05-13)

**Phase 3c CP14 — operator-only end-to-end smoke — CLOSED.** The
first real `/v1/messages` curl through the live server hit a P0
500 inside `AuthMiddleware.dispatch`. fly logs traceback:

```
asyncpg.exceptions.InsufficientPrivilegeError:
    permission denied to set role "llm_tracker_app"
[SQL: SET LOCAL ROLE llm_tracker_app]
File ".../llm_tracker_server/auth/middleware.py", line 83
```

Diagnosis via Supabase MCP `execute_sql` on `pg_auth_members`:
`postgres` was *already* a member of `llm_tracker_app` (Supabase
auto-grants `postgres` membership of newly created roles), but
with `admin_option=true, inherit_option=false, set_option=false`.
PG16 split role membership into three orthogonal options; the
pre-PG16 coupling of "membership implies SET ROLE" no longer
holds upstream. The auto-grant had INHERIT only — exactly the
combination that lets `current_user='postgres'` *see*
`llm_tracker_app`'s privileges (which is why CP5/CP6 passed
locally against `cp2` superuser-mode tests) but blocks
`SET LOCAL ROLE` (which is what RLS-enforcing auth middleware
actually needs).

Immediate unblock via Supabase MCP:

```sql
GRANT llm_tracker_app TO postgres WITH SET TRUE;
```

Post-grant `pg_auth_members` shows a second row with
`set_option=true, inherit_option=true` alongside the original
auto-grant row (Postgres ORs option rows; effective: all three
true). Cosmetic-only: the two rows could be collapsed via REVOKE
+ GRANT but behavior is unchanged.

Durable fix shipped as alembic migration `0006_grant_app_role_set`
(commit `458a4ba`):

- PG16+ branch: `GRANT llm_tracker_app TO CURRENT_USER WITH SET
  TRUE`
- PG15 branch: plain `GRANT llm_tracker_app TO CURRENT_USER`
  (the `WITH SET TRUE` qualifier is PG16+ only; would syntax-error
  on the local docker test fixture)
- Branch selector: `server_version_num >= 160000` inside a
  `DO $$ ... END $$` block; emit the right form per server.

`CURRENT_USER` (not hardcoded `postgres`) keeps the migration
portable across deploy environments where the connecting role
might be named differently. Live Supabase `alembic_version` is
still `0005` until the next `fly deploy` runs `alembic upgrade
head`; the migration is idempotent so the next deploy is a no-op
on the DB side and just advances the alembic stamp.

Verification:

```
$ # pre-fix (CP14 first attempt, operator-run curl)
HTTP/2 500 Internal Server Error

$ # post-fix invalid-token probe (no Anthropic key needed)
$ curl -X POST .../v1/messages -H "X-LLM-Tracker-Token: bogus" \
    -d '{"model":"claude-opus-4-5","max_tokens":1,"messages":[]}'
HTTP/2 403
{"detail":"unknown or revoked token"}

$ # post-fix real curl (operator-run, valid Anthropic key)
HTTP/2 200

$ # fly logs --since 5m (the 200 path)
proxy.forward (forwarded_credential: true)
HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
INFO: "POST /v1/messages HTTP/1.1" 200 OK
(no traceback)

$ # Supabase MCP: SELECT FROM exchanges ORDER BY started_at DESC
[1 row: id=01KRFVTG1E7Q72QN7E5MP26JXY,
 org_id=c6fcdd23-... (org_name="demo"),
 started_at=2026-05-13 05:09:16.974+00,
 endpoint=v1/messages, provider=anthropic, content_level=L3]

$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker_server/alembic/versions/0006_grant_app_role_set_membership.py
All checks passed!

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
61 passed in 25.70s
```

CP14's three success criteria from
`docs/worklog/2026-05-11-phase3c-plan.md`:

- ✅ Response stream returns to client unchanged (operator-confirmed
  200 + SSE bytes match Anthropic emit).
- ✅ Exactly one row lands in `public.exchanges` scoped to demo
  org. (Two demo-scoped rows total — the second is a 400-BadRequest
  debug row from the same session, also evidence that
  multi-tenancy isolation fires on every request regardless of
  upstream outcome.)
- ✅ `fly logs` since request timestamp shows no traceback.

**Secondary finding** (carved out per user direction as a separate
track): the successful row's response-side columns are all NULL —
`ended_at`, `model_requested`, `model_served`, `status_code`,
`input_tokens`, `output_tokens`, `latency_ms`, `stop_reason`. The
request-open INSERT works; the stream-close UPDATE that should
fill the response-side fields is silent on a 200-OK SSE. STATUS
CP9 had previously flagged `model_served=null` only for HTTP-error
(non-SSE) responses as a by-design observability hole; the current
finding extends that hole into the happy SSE path. Suspected
location: CP8's server-side plugin host port (`on_persisted` hook
dispatch) or CP9's storage UPDATE path. Owner of next CP / ADR
TBD — fresh worklog when picked up.

Phase 3c is **closed (operator smoke validated)**. The OAuth
Claude Code question that started this session is **not** yet
answerable in the affirmative — it remains gated on Phase 3b
(thin local agent or equivalent header-injection sidecar), which
itself is gated on Phase-3a items #1/#4. Operator-only smoke is
the proof-point for everything Phase-3c-rated, and that is now
in.

---

### Prior workstream — ADR-0023 server auth header rename (closed 2026-05-13)

**ADR-0023 — server auth header rename — landed (CP14 prep).** A
P0 blocker surfaced while preparing CP14: OAuth Claude Code users
(the majority) send their Anthropic credential in `Authorization:
Bearer <oauth-token>`. `AuthMiddleware` was reading the same slot
for our per-org token, eating the OAuth bearer and returning `403
unknown or revoked`. The local proxy never had this problem because
it was a transparent pass-through with no auth layer; the central
server is the first surface in this project that *consumes* a
header. ADR-0023 (commit `21e9fa5`) renames the server-auth header
to `X-LLM-Tracker-Token`; `Authorization` is now reserved for the
Anthropic credential pass-through (OAuth bearer, or absent for
`x-api-key` users) and flows through to upstream untouched.

Source change shipped in `af6bd8f`:

- `AuthMiddleware` reads `X-LLM-Tracker-Token` (was: `Authorization:
  Bearer ...`); the bearer-scheme parse is gone, the new header is
  a plain opaque value.
- `proxy.forwarder._LOCAL_ONLY = {"x-llm-tracker-token"}` (was:
  `{"authorization"}`). The strip set no longer touches
  `Authorization`, fixing the OAuth pass-through.
- Two new credential-passthrough tests pin the contract:
  `test_outbound_strips_x_llm_tracker_token` and
  `test_outbound_passes_authorization_bearer_through`.
- Module docstrings (`auth/__init__.py`, `auth/middleware.py`,
  `proxy/credential.py`, `proxy/forwarder.py`) updated; the
  Authorization-passthrough case is now explicit at every level.

Docs change in `21e9fa5`:

- ADR-0023 (Accepted) — amends ADR-0020 Axis 1 only; Axis 2
  (Anthropic credential pass-through) untouched.
- `docs/deploy.md` Step 5–6 curl + prose moved to
  `X-LLM-Tracker-Token`.
- `.env.example` Section 1 swapped; Section 2 extended to list
  `Authorization: Bearer <oauth-token>` as a third accepted form.

Verification (full transcript in worklog
`docs/worklog/2026-05-13-auth-header-rename.md` §Verification):

```
$ .venv/bin/python3.12 -m ruff check <7 modified files>
All checks passed!

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
............................................................. 61 passed in 23.04s
```

The "still on pre-rename build until next `fly deploy`" note that
sat here at finalize time turned out to be wrong: the rename build
was actually already live by the time CP14 started probing —
re-validated by the `missing X-LLM-Tracker-Token header` 401 body
in CP14's pre-flight probe.

---

### Prior workstream — Phase 3c CP13-b (closed 2026-05-13)

**Phase 3c CP13-b — first Fly.io + Supabase deploy — closed.**
The operator drove `docs/deploy.md` end-to-end. Two real-world
failures surfaced in flight and were fixed inside this session:

- **Failure 1: stale `public.exchanges` from the closed
  `supabase_sink` workstream.** The operator's Supabase project
  was the same one used by the Phase-2 `supabase_sink` plugin
  (closed 2026-05-08), which had created `public.exchanges` with
  an *incompatible* schema (`exchange_id` PK, `ts_started_ms`,
  `mode`, `source`, `request_text/response_text/raw_*`). The new
  server's `0001_initial_schema` collided
  (`DuplicateTableError: relation "exchanges" already exists`)
  on first `fly deploy`. Diagnosis confirmed via Supabase MCP
  `list_tables` (single stale table, 7 rows, no `alembic_version`
  yet, no trigger function) — i.e. nothing of the new schema had
  partially applied. Dropped the stale table via MCP
  `execute_sql DROP TABLE public.exchanges CASCADE` after
  confirming with the user that ADR-0007's plugin data is not
  load-bearing (ADR-0017 supersedes ADR-0007; the plugin's
  `schema.sql` is checked in so a future revival can rebuild a
  fresh sink target without depending on these rows). Second
  `fly deploy` ran `alembic upgrade head` cleanly through 0001
  → 0005; both `nrt` Machines passed `/healthz`.
- **Failure 2: asyncpg / pgbouncer transaction-mode prepared-
  statement clash.** After migrations applied, `alembic current`
  (and any DB-touching application route) failed with
  `asyncpg.exceptions.DuplicatePreparedStatementError: prepared
  statement "__asyncpg_stmt_1__" already exists`. Cause: Supabase's
  pooled URL (Transaction mode pgbouncer) does not preserve
  prepared statement names across pooled sessions, while asyncpg
  caches them by default. Fix shipped in commit `3050bcc`
  (`server: pgbouncer transaction-mode compat (CP13-b)`):
  `connect_args={"statement_cache_size": 0}` passed through both
  `make_engine()` and `alembic/env.py` `create_async_engine`.
  No-op against direct PG (the local Docker test fixture); the
  single-token-of-effect lives in `make_engine` so it covers the
  server, the `llm-tracker-server tokens issue` CLI, and the test
  fixtures uniformly. Initial false-start (also passing
  `prepared_statement_cache_size=0` as a top-level kwarg) was
  reverted — that is a URL-level dialect parameter, not an
  engine kwarg, and the root-cause error name (`__asyncpg_stmt_N__`)
  pointed at asyncpg's cache only.

Verification (post-deploy, full transcript in worklog
§Verification):

```
$ fly ssh console -C "alembic current"
0005_rls_policies (head)

$ curl -i https://llm-tracker-server.fly.dev/healthz
HTTP/2 200 ...
{"status":"ok","version":"0.0.1"}

$ for i in 1 2 3; do curl -s -o /dev/null -w "HTTP %{http_code}\n" \
   -X POST https://llm-tracker-server.fly.dev/v1/messages \
   -H "Content-Type: application/json" \
   -d '{"model":"claude-opus-4-5","max_tokens":1,"messages":[]}'; done
HTTP 401   HTTP 401   HTTP 401
```

Supabase schema state (via MCP `list_tables`, post-deploy):

```
public.alembic_version  (1 row, version_num = 0005_rls_policies)
public.exchanges        (RLS on,  0 rows)
public.events           (RLS on,  0 rows)
public.tool_calls       (RLS on,  0 rows)
public.audit_log        (RLS on,  0 rows)
public.orgs             (RLS off — substrate, by design 0005)
public.api_tokens       (RLS off — substrate, by design 0005)
```

CP13-b-specific decisions captured in the worklog
`docs/worklog/2026-05-13-cp13b-fly-deploy.md` §Decisions; the
load-bearing ones:

1. **Same Supabase project, drop the stale plugin table.** Plugin
   workstream is closed; rows are not load-bearing; spinning up
   a new Supabase project would have doubled secrets + budget for
   no benefit.
2. **Disable asyncpg's prepared-statement cache at the engine
   layer**, not via URL query parameter. Single point of effect
   across all callers; portable across deploy environments;
   `LLMTRACK_DATABASE_URL` secret stays untouched.
3. **Did not also disable SQLAlchemy's compiled prepared-statement
   cache.** The reproducible failure was asyncpg's
   `__asyncpg_stmt_N__` only; verified by three consecutive
   `/v1/messages` 401s post-fix.
4. **Did not auto-apply the Supabase RLS advisor remediation SQL.**
   Advisor flagged `alembic_version`, `orgs`, `api_tokens` as
   RLS-disabled. `alembic_version` is alembic-internal;
   `orgs`/`api_tokens` are *intentionally* RLS-disabled per the
   0005 docstring (tenancy substrate the auth path needs to read
   before any RLS context is set). The advisor's concern is
   PostgREST-anon exposure — not used by this server, but a
   defense-in-depth follow-up CP is owed (REVOKE anon/authenticated
   or RLS-with-`llm_tracker_app`-only policy). Surfaced; not
   acted on.

Source HEAD is now `3050bcc`. Documentation HEAD advances with
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
| 2 | Consent + data-handling policy | **Settled 2026-05-17** | **ADR-0029** |
| 3 | Agent-to-server auth model | **Settled 2026-05-11** | **ADR-0020** |
| 4 | Local agent language/distribution | **Pending** (defers Phase 3b; not on critical path under server-first reframe) | — |
| 5 | Multi-tenancy boundary | **Settled 2026-05-11** | **ADR-0018** |
| 6 | What survives of ADR-0006 L/A/R modes | **Settled 2026-05-11** | **ADR-0019** |
| 7 | What survives of ADR-0008 signing | **Settled 2026-05-11** — fully retired | **ADR-0021** |

Items 1 and 4 do **not** block Phase 3c (server build-out): the
server can be built against ADR-0018/0019/0020 schemas and surfaces
without resolving them. Item #2 (consent + data-handling) is **now
settled** by ADR-0029, so external (non-team) testing is no longer
blocked on policy — operator-deploy of the new image is the
operational next step.

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

**Operator deploy of `a4c08b3` to Fly** to pick up the new scrubber
on production traffic. No code-side changes are owed; the next
`fly deploy` picks up the new SDK that `analytics_sink` and
`keyword_block` already import. Post-deploy, the operator can
confirm on a fresh `plugin_analytics` row that any sensitive tokens
echoed in a tool_result or user prompt come back as `[REDACTED:…]`
tags through the `ctx.request_text()` / `ctx.response_content_json()`
accessors (rows in the database itself remain canonical — that is
the documented storage-vs-accessor asymmetry, see
`docs/plugins.md` §3.2).

Once the deploy lands, the next blocking item moves down to one of
the queued follow-ups below.

Queued follow-ups (none gate the deploy step above; safe to interleave):

- **Pre-SSE upstream-failure-path row write** (ADR-0027 axis 2 impl).
  Today an upstream failure before the first SSE event yields no
  `public.exchanges` row at all; the open-INSERT happens after the
  bytes start flowing. ADR-0027 axis 2 names the desired behavior.
- **`exchanges.tool_call_count` fate.** Still at the `0` placeholder
  — derive via `jsonb_path_query` on `response_json.content`, or
  deprecate / drop the column. Separate decision.
- **`docs/deploy.md` paragraph on PG16+ `set_option` quirk.** Sits
  naturally next to the existing pgbouncer/asyncpg note from
  CP13-b. Any future PG16+ managed deploy (RDS, Cloud SQL, Neon)
  will hit the same trap.

### Side-quests (do at any time, none blocking)

- ~~**Stamp migration 0006 on live Supabase.**~~ **Closed** by this
  checkpoint's `fly deploy` (release-command-run `alembic upgrade
  head` advanced `alembic_version` to `0006_grant_app_role_set`).
- ~~**ADR-#2 consent + data-handling.**~~ **Closed 2026-05-17** by
  ADR-0029 (six-axis policy + SDK accessor scrubber). External
  testing is no longer policy-blocked; operator-deploy of `a4c08b3`
  is the operational next step.
- **`docs/deploy.md` paragraph on PG16+ `set_option` quirk.** Sits
  naturally next to the existing pgbouncer/asyncpg note from
  CP13-b. Any future PG16+ managed deploy (RDS, Cloud SQL, Neon)
  will hit the same trap.

### Local dev loop revival (still current)

To revive the local dev loop in a new session (Postgres on the
host for the test-fixture suite; the Dockerised server +
Fly.io deployment are independent):

```
docker run -d --name llm-tracker-pg \
  -e POSTGRES_USER=cp2 -e POSTGRES_PASSWORD=cp2 \
  -e POSTGRES_DB=llm_tracker_test \
  -p 55432:5432 postgres:15
export LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test
```

To rebuild + smoke the CP12 image locally:

```
docker build -t llm-tracker-server:local .
docker run -d --rm -p 18080:8080 --name lts-smoke llm-tracker-server:local
curl -sS http://localhost:18080/healthz
docker stop lts-smoke
```

The user-deferred items #1 (fallback) and #4 (agent language) are
**not on the critical path** under the current server-first
reframe; they re-enter the queue once Phase 3b (thin agent) is
ready to start.

## Blocking / decisions needed

- **#2 consent + data-handling**: **Settled 2026-05-17 by ADR-0029.**
  External (non-team) testing is no longer blocked on policy;
  operator-deploy of `a4c08b3` is the operational next step before
  routing external traffic.
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
- [x] **Phase 3c CP13-a — `fly.toml` + `docs/deploy.md` (2026-05-13, commits ef59192 + 59dbae6)**
- [x] **Phase 3c CP13-b — first Fly.io + Supabase deploy (2026-05-13, commit 3050bcc; server live at `https://llm-tracker-server.fly.dev/`)**
- [x] **ADR-0023 — server auth header rename to `X-LLM-Tracker-Token` (2026-05-13, commits af6bd8f + 21e9fa5; CP14 prep, fixes OAuth Claude Code collision)**
- [x] **Phase 3c CP14 — operator-only end-to-end smoke (2026-05-13, commit 458a4ba; first 200-OK roundtrip with operator-minted demo token; demo-scoped row in `public.exchanges`; PG16+ deploy gap surfaced + fixed in migration 0006; response-side metadata NULL on the success row flagged as separate follow-up track)**
- [x] **CP14 follow-up Option A — close-out columns populated (`ended_at`/`status_code`/`model_requested`/`latency_ms`) (2026-05-13, commit 237d842; production-verified on row `01KRG14W5VNV78HN3P9PEF2Z9P` after `fly deploy` — same deploy stamped `alembic_version` to `0006_grant_app_role_set`; investigation falsified the prior "INSERT-at-open + UPDATE-at-close" hypothesis — there is no UPDATE path; 4 of 8 response-side NULLs closed; remaining 5 (`model_served`, `input_tokens`, `output_tokens`, `cache_*`, `stop_reason`) need Option B's SSE Extractor)**
- [x] **Option B + plugin-ecosystem workstream (2026-05-14, commits `f02f516` α / `61c8aeb` β / `49804f5` γ / `b3f9ed2` δ / `7741c13` ε / `854d4ee` ζ); ADR-0026 (HookContext response accessors) + ADR-0027 (exchange row close-out policy) Accepted; `extractors/anthropic.py` populates the five SSE-derived columns end-to-end on the happy path; migration 0007 adds `plugin_analytics`; `analytics_sink` writes one row per exchange; `keyword_block` polished from TEST-ONLY to operator-configurable; Docker image bundles both plugins. **Production-validated 2026-05-16 by operator smoke** (post-deploy `plugin_analytics` row carried all five columns populated with `usage.input_tokens=6 / output_tokens=152 / cache_read=75512 / cache_creation=133` under `stop_reason=tool_use`).**
- [x] **ADR-0028 follow-up — extractor faithful reassembly (2026-05-16, commit `8138d91`); `response_json` now captures tool_use, thinking, signature, and unknown future block types instead of text-only; surfaced by a live `plugin_analytics` row whose `content: []` had silently dropped a 112-token tool_use payload. Full repo test suite 334 passed under the DB fixture (+5 new tests). **Production-validated 2026-05-16 in the same operator-smoke window** — verbatim row carried both a thinking block (signature preserved) and a tool_use block with `input` as a parsed dict (no `_input_json_raw` fallback). `keyword_block` also exercised live via `LLMTRACK_KEYWORD_BLOCK_LIST = "no_response"` in `fly.toml`.**
- [x] **ADR-0029 — consent + data-handling policy + HookContext accessor-level scrubber (2026-05-17, commit `a4c08b3`); six-axis decision packet (full L3 storage / docs-only disclosure / 6-month retention / operator-handled deletion / `sk-`+`lts_`+`Bearer`+email scrubbing / SDK-accessor location) lands as Accepted ADR plus `llm_tracker_sdk.scrubbers` + HookContext wiring + `docs/deploy.md` "Data collection & privacy" section + `docs/plugins.md` §3.2. Test suite 354 passed under DB fixture (+20 new). External (non-team) testing no longer blocked on policy — operator-deploy of the new image is the operational step that brings the scrubber to production.**
- [ ] **Phase 3a — remaining 2 decision ADRs** (#1 fallback / #4 agent language)
- [ ] Phase 3b — thin local agent (gated on #1 + #4)
- [x] **Phase 3c — server build-out (14 of 14 plan-checkpoints done; closed 2026-05-13 with operator smoke validated. Plan at `docs/worklog/2026-05-11-phase3c-plan.md`, anchored on ADR-0017/0018/0019/0020/0022/0023)**
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
