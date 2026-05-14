# 2026-05-14 · Plugin ecosystem — Option B SSE extractor + analytics_sink + keyword_block

**Author**: Claude Code
**Session trigger**: Multi-checkpoint task — Option B SSE Extractor + `analytics_sink`
plugin + `keyword_block` plugin promotion + Dockerfile/fly.toml bundling. ADR-0026
(HookContext response accessors) and ADR-0027 (exchange row close-out policy) gate
the code changes per CLAUDE.md §4 (HookContext is a public interface).
**Related docs**: `docs/decisions/0026-hookcontext-response-accessors.md` (new),
`docs/decisions/0027-exchange-row-close-out-policy.md` (new),
`docs/worklog/2026-05-13-phase3b-agent.md` (prior session), STATUS.md ("Next
single step" before this session = ADR-0026/close-out policy).

## Interpretation

The task as written said "Write `docs/decisions/0024-hookcontext-response-accessors.md`"
and "Do not touch ... `docs/decisions/` files other than 0024." Two collisions with
the live repo:

- ADR-0024 was already taken by the Phase-3b agent fail-closed ADR
  (commit `79a0ae9`). Overwriting it would erase a load-bearing decision.
- STATUS.md (commit `55cb2e3`, same session lineage) explicitly queued a separate
  ADR — "exchange row close-out policy" — as the *prerequisite* to Option B, so the
  second signature extension on `record_exchange_timing` lands under a stable
  contract. The task skips this ADR entirely.

Surfaced both to the user via `AskUserQuestion`. The user picked **ADR-0026** for
the HookContext accessors ADR and **bundled in this session** the close-out policy
ADR (now **ADR-0027**), so both ADRs land before the code-touching β/γ/δ/ε/ζ
checkpoints. The user also picked all three "recommended" answers for ADR-0027's
substantive decisions (best-effort NULL on response side, write a row on pre-SSE
upstream failure, pull `ended_at`/`latency_ms`/`model_requested` into the blocked
helper).

Other reinterpretations from the task as written:

- `inpokens` → `input_tokens` (typo); `thr` → `the`; `contnt` → `content`;
  `t_tokens` → `input_tokens`; `ugin.py` → `plugin.py`; `init.py` → `__init__.py`;
  `hook"on_request_received"]` → `hooks = ["on_request_received"]`;
  `https://-tracker-server.fly.dev` → `https://llm-tracker-server.fly.dev`.
- Anthropic's standard SSE puts cache tokens in
  `message_start.message.usage.cache_read_input_tokens` /
  `cache_creation_input_tokens` (the task's `ca_tokens` is a truncation); the
  extractor reads the canonical names.
- `keyword_block` is already a proper package (`packages/llm_tracker_plugin_keyword_block/`)
  — the task's "promote from test harness" framing is outdated by one Phase-2
  workstream. The ε checkpoint becomes: rename `LLMTRACK_KEYWORDS_BLOCK_LIST` →
  `LLMTRACK_KEYWORD_BLOCK_LIST` (canonical name per task), default to empty list
  (was: two built-in test defaults), refresh docstrings to drop "TEST-ONLY"
  framing now that it ships in the server image.

## What was done

### Checkpoint α — ADR-0026 + ADR-0027 (commit `f02f516`)

- Created `docs/decisions/0026-hookcontext-response-accessors.md` — Accepted.
  Amends ADR-0012; adds `_parsed_response: object | None` field +
  `response_usage()` / `response_content_json()` accessors + `org_id` field on
  `HookContext`. Settles STATUS.md "Phase 1c prerequisites" response-side
  bullet for the L3 case.
- Created `docs/decisions/0027-exchange-row-close-out-policy.md` — Accepted.
  Three axes settled: best-effort NULL on response-side columns; write a row
  on pre-SSE upstream failure (documented; impl is a follow-up checkpoint
  under this ADR's banner); pull `ended_at`/`latency_ms`/`model_requested`
  into `record_exchange_blocked` (impl in checkpoint β alongside the helper
  signature change).
- Created this worklog scaffold (`docs/worklog/2026-05-14-plugin-ecosystem.md`).

### Checkpoint β — SSE extractor + SDK + forwarder + storage (commit `61c8aeb`)

- Created `packages/llm_tracker_server/src/llm_tracker_server/extractors/__init__.py`
  and `extractors/anthropic.py` — the parser + dataclasses
  (`ResponseUsage`, `ParsedResponse`, `parse_sse_stream`). ~135 lines
  excluding docstrings; never raises; handles `message_start` /
  `message_delta` / `content_block_delta` + assembles `response_json`
  to the non-stream Anthropic shape.
- Modified `packages/llm_tracker_sdk/src/llm_tracker_sdk/hook_context.py`
  — added `org_id: uuid.UUID | None` and
  `_parsed_response: object | None` fields plus `response_usage()` /
  `response_content_json()` read-only accessors (ADR-0026 surface).
- Modified `packages/llm_tracker_server/src/llm_tracker_server/storage/exchanges.py`
  — `record_exchange_timing` gains six keyword-only params
  (`model_served`, `input_tokens`, `output_tokens`, `cache_read_tokens`,
  `cache_write_tokens`, `stop_reason`), each defaulting to None.
  `record_exchange_blocked` gains `ended_at_ms`, `latency_ms`,
  `model_requested` per ADR-0027 axis 3.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py`
  — replaced `_drain` no-op with `parse_sse_stream`; stashed parsed
  result on per-exchange ctx; threaded six new args into the timing
  helper; threaded three new args into all three `record_exchange_blocked`
  call sites via a small `_close_out_now()` closure; set
  `ctx.org_id = org_id` after `begin_exchange`.
- Created `packages/llm_tracker_server/tests/test_sse_extractor.py`
  — 6 tests: realistic stream, truncated stream (no-raise),
  malformed JSON, assembled `response_json`, byte-boundary splits,
  empty stream.

### Checkpoint γ — alembic migration 0007 (commit `49804f5`)

- Created `packages/llm_tracker_server/alembic/versions/0007_plugin_analytics.py`
  — new `plugin_analytics` table (ULID PK, `org_id` FK to
  `orgs(id)`, request/response JSON columns + extractor token
  counts + `stop_reason` + `tool_call_count`). No FK on
  `exchange_id` (ordering not enforced); no RLS (internal
  analytics, not user-data scoped); indices on `org_id` and
  `created_at`. Idempotent up/down: round-tripped via
  `alembic downgrade -1` + `alembic upgrade head`.

## Decisions

- **ADR number split**: HookContext response accessors → ADR-0026; exchange row
  close-out policy → ADR-0027. ADR-0024 stays as agent fail-closed (commit
  `79a0ae9`). Confirmed with the user via `AskUserQuestion`.
- **ADR-0027 §"Decision"**:
  1. Best-effort NULL on response-side columns (`model_served`, `input_tokens`,
     `output_tokens`, `cache_*`, `stop_reason`) — extractor never raises; missing
     fields stay NULL.
  2. Pre-SSE upstream failure path writes a row anyway with `status_code` +
     `ended_at` + `model_requested` + `latency_ms` populated. Response-side
     fields NULL. Today the pre-SSE-failure path has no INSERT at all.
  3. Blocked-path parity: pull `ended_at_ms` + `latency_ms` + `model_requested`
     into `record_exchange_blocked` so blocked rows are queryable on the same
     axes as happy-path rows.

## Verification

### Checkpoint β

```
$ .venv/bin/python3.12 -m ruff format \
    packages/llm_tracker_server/src/llm_tracker_server/extractors/ \
    packages/llm_tracker_server/src/llm_tracker_server/proxy/forwarder.py \
    packages/llm_tracker_server/src/llm_tracker_server/storage/exchanges.py \
    packages/llm_tracker_sdk/src/llm_tracker_sdk/hook_context.py \
    packages/llm_tracker_server/tests/test_sse_extractor.py
1 file reformatted, 5 files left unchanged

$ .venv/bin/python3.12 -m ruff check <same paths>
All checks passed!

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
51 passed, 16 skipped in 5.82s

$ LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q
67 passed in 21.97s
# includes test_two_org_e2e_isolation through the new extractor.

$ .venv/bin/python3.12 -m pytest -q   # full repo
308 passed, 16 skipped, 4 warnings in 12.98s
# 6 new SSE-extractor tests; was 302 before this checkpoint.
```

### Checkpoint γ

```
$ LLMTRACK_DATABASE_URL=postgresql+asyncpg://cp2:cp2@localhost:55432/llm_tracker_test \
    .venv/bin/python3.12 -m alembic upgrade head
INFO  Running upgrade  -> 0001_initial_schema
INFO  Running upgrade 0001_initial_schema -> 0002_audit_log_triggers
INFO  Running upgrade 0002_audit_log_triggers -> 0003_orgs_and_tokens
INFO  Running upgrade 0003_orgs_and_tokens -> 0004_org_id_on_user_data
INFO  Running upgrade 0004_org_id_on_user_data -> 0005_rls_policies
INFO  Running upgrade 0005_rls_policies -> 0006_grant_app_role_set
INFO  Running upgrade 0006_grant_app_role_set -> 0007_plugin_analytics

$ alembic current
0007_plugin_analytics (head)

$ alembic downgrade -1
INFO  Running downgrade 0007_plugin_analytics -> 0006_grant_app_role_set

$ alembic upgrade head
INFO  Running upgrade 0006_grant_app_role_set -> 0007_plugin_analytics

$ LLMTRACK_TEST_DATABASE_URL=... .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_server/tests -q
67 passed in 22.19s
```

## What's left / known limits

- Checkpoint δ — `analytics_sink` plugin package.
- Checkpoint ε — `keyword_block` plugin polish (env var rename, default
  empty, drop "TEST-ONLY" framing).
- Checkpoint ζ — Dockerfile + fly.toml bundling.
- Pre-SSE failure-path row write (ADR-0027 axis 2 impl) — deferred to a
  follow-up checkpoint after ζ ships.
- Tool-use extraction (`tool_call_count > 0` on `exchanges` and
  `plugin_analytics`) — extractor currently parses text content only;
  flagged in `extractors/anthropic.py` docstring.

## Handoff

Checkpoints β + γ shipped (`61c8aeb`, `49804f5`). Schema is now in
place for the `analytics_sink` plugin; checkpoint δ is unblocked.
