# 2026-05-17 · Queued follow-up batch (4 of 5 done; 1 returned to queue)

**Author**: Claude Code
**Session trigger**: User asked to clear the five queued follow-ups
listed in `2026-05-17-adr-0029-production-smoke.md` §"What's left" in
one batch, surfacing only the decisions that actually needed user
input. The session executed four of the five.
**Related docs**: ADR-0027 (close-out policy, axis 2 implementation),
ADR-0028 §Non-goals (tool_call_count placeholder posture),
`packages/llm_tracker_server/alembic/versions/0007_plugin_analytics.py`
(the migration whose docstring overturned the RLS premise),
`packages/llm_tracker_server/alembic/versions/0008_drop_tool_call_count.py`
(new), prior worklog
`docs/worklog/2026-05-17-adr-0029-production-smoke.md`.

## Interpretation

The five queued items at session start:

1. `plugin_analytics` RLS policy.
2. ADR-0027 axis 2 impl (pre-SSE upstream-failure-path row write).
3. `exchanges.tool_call_count` fate (deprecate / drop / leave).
4. `docs/deploy.md` PG16+ `set_option` quirk paragraph.
5. Empty package-directory shells cleanup.

User decisions surfaced before execution:

- **`tool_call_count` fate (Option C)**: drop the column entirely.
  ADR-0028 §Non-goals + ADR-0027 §Open questions had already
  documented the "stays 0; derive at query time" posture; the user
  picked drop over leave.
- **RLS axis (Option A)**: exclude `plugin_analytics` RLS from this
  batch + correct STATUS. The exploration uncovered that 0007's
  docstring explicitly chose "no RLS on this table" with reasoning
  ("Analytics is internal — the plugin queries this directly from
  operator tooling without going through the request-scoped
  session"); the advisor's "newly surfaced gap" framing I had used
  in STATUS was factually wrong. The decision to enable RLS would
  reverse a deliberate-but-not-ADR-elevated choice and is therefore
  ADR-level work, deferred.

The remaining four were strictly executable (ADR-0027 has 599 sentinel
+ population matrix already specified; the docs paragraph is a
pull-from-CP14 finding; the cleanup is `rm -rf` on empty shells).

## What was done

Four commits in order:

### 1. `1a886e6` — docs: deploy.md — PG16+ membership WITH SET paragraph

New section between the pgbouncer/asyncpg note and "A subsequent
deploy needs a fresh secret." Names the PG16 split of role
membership into (admin / inherit / set), the Supabase auto-grant
pattern that gives only `inherit_option`, the
`InsufficientPrivilegeError` symptom, and the conditional fix in
migration `0006_grant_app_role_set` (PG16+ uses `WITH SET TRUE`;
PG15 uses plain GRANT). Closes the future-deploy gap: any operator
deploying to a fresh PG16+ managed service (RDS, Cloud SQL, Neon)
now has the trap and the cure in one place.

### 2. (cleanup, no commit) — empty package-directory shells removed

`packages/llm_tracker/` and `packages/llm_tracker_plugin_supabase_sink/`
contained zero git-tracked files (the housekeeping CP earlier today
deleted them) but the working tree still held empty subdirectories
plus stale `__pycache__/*.pyc` files. `rm -rf` on both — git status
unchanged (the .pyc files were `.gitignore`'d). No commit lands
because no tracked file changed.

### 3. `7b20125` — server: drop exchanges.tool_call_count (migration 0008)

- Migration `0008_drop_tool_call_count` — `op.drop_column` upgrade
  + `op.add_column(... NOT NULL DEFAULT 0 ...)` downgrade. Down
  revision is `0007_plugin_analytics`.
- `storage.models.Exchange`: dropped the mapped column.
- `storage.exchanges`: dropped `tool_call_count=0` from both
  `record_exchange_timing` and `record_exchange_blocked` INSERTs.
- `tests/test_storage_smoke.py`, `tests/test_org_id_constraint.py`
  (×2 occurrences), `tests/test_rls_two_org_isolation.py`: dropped
  the placeholder from `Exchange()` constructors.
- `public.plugin_analytics.tool_call_count` is a separate
  plugin-owned surface; intentionally left untouched.

### 4. `0db0bac` — server: ADR-0027 axis 2 — pre-SSE upstream failure path

- New helper `storage.exchanges.record_exchange_failure(session, *,
  exchange_id, org_id, endpoint, started_at_ms, ended_at_ms,
  latency_ms, model_requested, status_code)`. Shape parallels
  `record_exchange_blocked`: same close-out fields, plus
  `status_code` (required on this path), no `blocked_by` (upstream
  not delivering is not a plugin decision).
- `proxy/forwarder.py` — wrapped `http_client.send` in
  `try / except httpx.RequestError` for the network-error path, and
  added a `status_code != 200` short-circuit immediately after for
  the upstream-non-2xx path. Both paths:
  - Write the row via `record_exchange_failure` under
    `has_request_scope` (only present when `AuthMiddleware` ran).
  - Call `plugin_host.end_exchange(exchange_id)` explicitly because
    the streaming generator's `finally` clause is what normally
    cleans up the per-exchange ctx and never runs on these
    short-circuit paths.
  - Skip `on_upstream_response_start` — the request never reached
    the SSE shape that hook is contractually about.
- `599` is the documented "upstream gave us nothing" sentinel per
  ADR-0027 §"Open questions"; surfaced when `httpx.RequestError`
  fires (ConnectError, TimeoutException, ReadError, etc.).
- Two new forwarder-level tests:
  - `test_axis2_non_200_short_circuits_with_status` — upstream 401
    forwarded verbatim, SSE-only hooks not fired, ctx cleaned.
  - `test_axis2_upstream_connection_error_returns_503` — upstream
    `ConnectError` returns 503 to client, SSE-only hooks not fired,
    ctx cleaned.

The DB-write half of `record_exchange_failure` runs only under the
auth-middleware shape and is covered by future DB-fixture integration
tests; this CP intentionally adds forwarder-level behaviour tests
under the no-auth shape, matching the pattern of
`test_proxy_forwarder_hooks.py`.

## Decisions

- **`tool_call_count` drop, not deprecate/leave.** Two ADRs already
  documented the column had no real populator and the operator query
  was one `jsonb_path_query` away. Keeping it as a 0 placeholder
  would have left the same false-zero footgun that motivated
  ADR-0028's faithful-reassembly contract — a user reading
  `tool_call_count = 0` on a tool-use row would still draw the wrong
  conclusion. Drop is the cleanest write.
- **`plugin_analytics` RLS deferred, not refused.** The session
  surfaced that 0007's docstring made a deliberate "no RLS on this
  table" choice. Reversing it would re-open the question of how
  operator tooling queries internal analytics tables under a
  session-bound RLS shape — that is ADR-level work (separate axis
  from ADR-0018's user-data RLS guarantee). Surfaced + queued, not
  resolved.
- **PG16+ paragraph location in deploy.md.** Slots immediately after
  the pgbouncer/asyncpg note so the troubleshooting flow covers both
  PG16+ traps the project has hit in one read-through. The
  alternative ("split into a fresh top-level §") would have spread
  related traps across the doc.
- **`record_exchange_failure` signature parallels `_blocked`, not
  `_timing`.** The shorter helper is the right reference: blocked
  rows and failure rows both share "the request never reached the
  SSE shape." Cloning `_timing` would have inherited the six
  best-effort-NULL params the failure path can never populate
  (extractor never ran).
- **No `plugin_host` hook on the axis-2 path.** ADR-0027 axis 2 is
  silent on plugin behaviour; following the ADR's narrow scope kept
  the diff small. If a future ADR wants a plugin to see "the
  request failed upstream," it can introduce a new hook rather than
  overloading `on_upstream_response_start` with a meaning it does
  not have today.
- **Explicit `end_exchange` on short-circuit paths.** The streaming
  generator's `finally` is the only place that cleans up the ctx
  under the existing happy/Block/Abort shapes; adding two new
  short-circuit returns without explicit cleanup would leak a ctx
  per axis-2 row. The Block/Abort paths share this latent
  ctx-cleanup gap on the existing code — out of scope for ADR-0027
  axis 2 + flagged as a follow-up.

## Verification

Ruff (all modified files clean after the auto-fix `--fix` run on
0008's import sort, then ruff format on the test file):

```
$ .venv/bin/python3.12 -m ruff check <modified files>
All checks passed!
$ .venv/bin/python3.12 -m ruff format --check <modified files>
N files already formatted
```

Tests (no-DB; DB-fixture tests still skip under
`LLMTRACK_TEST_DATABASE_URL` absence — unchanged):

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
58 passed, 16 skipped in 5.50s
# Was 56 / 16 — +2 axis 2 forwarder tests.
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests/test_proxy_forwarder_hooks.py -q
9 passed in 0.15s
```

Working tree (post-cleanup):

```
$ ls packages/
llm_tracker_agent              llm_tracker_plugin_keyword_block
llm_tracker_plugin_analytics_sink  llm_tracker_plugin_token_counter
llm_tracker_plugin_hello_world llm_tracker_sdk
llm_tracker_server
```

Seven packages, the two stale shells gone.

## What's left / known limits

- **`plugin_analytics` RLS** returned to queue as an ADR-level
  question (separate axis from ADR-0018). The 0007 migration's
  in-docstring decision should be either elevated to an ADR or
  reconsidered with an explicit policy on how operator tooling
  queries internal analytics tables under a session-bound shape.
- **DB-fixture integration tests for axis 2** — the
  `record_exchange_failure` write path runs only under the
  auth-middleware shape, which the no-DB test pattern in
  `test_proxy_forwarder_hooks.py` does not exercise. A future
  DB-fixture test (alongside `test_storage_smoke.py` etc.) can
  pin the row shape directly. Not blocking the deploy.
- **Block/Abort ctx-cleanup latent gap.** The existing Block/Abort
  short-circuit returns also lack explicit `end_exchange` because
  the streaming generator's `finally` does not run on them either.
  Surfaced while implementing axis 2; out of scope for this CP
  (separate small follow-up).
- **6-month automated retention deletion job** (ADR-0029 Axis 3)
  and **real `session_id` populator + deletion endpoint**
  (ADR-0029 Axis 4) — unchanged from prior closures.

## Handoff

CP commits, in order:

```
1a886e6   docs: deploy.md — PG16+ membership WITH SET paragraph
7b20125   server: drop exchanges.tool_call_count (migration 0008)
0db0bac   server: ADR-0027 axis 2 — pre-SSE upstream failure path
<finalize>   docs: STATUS + worklog — followup batch
```

After the next `fly deploy`, two operational consequences:

1. `alembic upgrade head` advances `alembic_version` to
   `0008_drop_tool_call_count`, ALTER-TABLE drops the column. The
   table is small; the DDL holds an ACCESS EXCLUSIVE on
   `public.exchanges` for the duration but should complete in
   well under a second on a 30-row table.
2. Any upstream pre-SSE failure (Anthropic 4xx/5xx pre-SSE, or
   network error against the upstream) now writes a
   `public.exchanges` row instead of being invisible to the fact
   table. Operator queries like `WHERE status_code BETWEEN 500 AND
   599` and `WHERE status_code = 599` (network errors) become
   meaningful.

Queued follow-ups for the next session (none gate any next CP):

- `plugin_analytics` RLS axis: ADR or explicit confirmation of the
  0007 docstring's posture.
- Block/Abort ctx-cleanup small fix (out of scope here).
- DB-fixture integration tests for `record_exchange_failure`.
- 6-month automated retention deletion job.
- Real `session_id` populator + deletion endpoint.
- i18n email scrubbing.
