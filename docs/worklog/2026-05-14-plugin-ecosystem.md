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

### Checkpoint δ — analytics_sink plugin (commit `b3f9ed2`)

- New package `packages/llm_tracker_plugin_analytics_sink/`:
  `pyproject.toml`, `plugin.toml`, `__init__.py`, `plugin.py`,
  `tests/test_analytics_sink.py` (5 tests).
- Plugin owns its own async engine
  (`LLMTRACK_DATABASE_URL` + `statement_cache_size=0` for
  pgbouncer transaction-mode), stashes the request body + the
  extracted Anthropic system prompt on `on_request_received`,
  and writes one row to `plugin_analytics` on `on_persisted`.
  Reads `ctx.org_id` + `ctx.response_usage()` +
  `ctx.response_content_json()` via the ADR-0026 accessors.
- System-prompt extraction handles all three Anthropic shapes:
  top-level `system` string, top-level `system` list of blocks,
  legacy `messages[0]` with role="system".
- Defensive guards: skips silently when `ctx.org_id` is missing
  or the engine is disabled.
- Root `pyproject.toml` testpaths gains the new tests dir; uv
  workspace auto-discovers + installs the package via `uv sync`.

### Checkpoint ε — keyword_block plugin polish (commit `7741c13`)

- Renamed env var `LLMTRACK_KEYWORDS_BLOCK_LIST` →
  `LLMTRACK_KEYWORD_BLOCK_LIST` (canonical singular; no
  production consumers to migrate).
- Changed `DEFAULT_KEYWORDS` from
  `("forbidden_word", "do_not_send")` → `()`. Empty default
  means the plugin loads but never blocks unless the operator
  supplies a non-empty list. The TEST-ONLY framing in the
  docstring + `pyproject.toml` description was scrubbed; the
  package now ships in the central server's Docker image
  alongside `analytics_sink`. `version`: `0.0.1` → `0.1.0`.
- `plugin.toml`: `capabilities = []` (server-side host ignores
  capabilities per ADR-0019); `allowed_modes = ["R"]`;
  `min_content_level = "L3"`; description rewritten.
- Tests updated for new env-var name + empty-default
  expectations. 9 tests pass.

### Checkpoint ζ — Dockerfile + fly.toml (commit `854d4ee`)

- Dockerfile: builder stage COPY + `pip install` for both
  new plugin packages.
- `.dockerignore`: dropped the keyword_block exclusion;
  `analytics_sink` was never excluded. `tests/` subtrees of
  both plugin packages added to the exclusion list.
- fly.toml `[env]`: `LLMTRACK_KEYWORD_BLOCK_LIST = ""` declared
  explicitly. `analytics_sink` reads `LLMTRACK_DATABASE_URL`
  which is already a fly secret — no fly.toml change.
- Image build verified locally (`docker build -t
  llm-tracker-server:zeta .`); inside the image, the plugin
  entry-points discovery returns
  `['analytics_sink', 'keyword_block']`; `/healthz` returns
  `{"status":"ok"}` after `docker run`.

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

### Checkpoint δ

```
$ uv sync
... + llm-tracker-plugin-analytics-sink==0.1.0

$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker_plugin_analytics_sink
All checks passed!

$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_plugin_analytics_sink/tests -q
5 passed in 0.28s

$ LLMTRACK_TEST_DATABASE_URL=... .venv/bin/python3.12 -m pytest -q
329 passed, 4 warnings in 30.06s
# Was 308 before δ (no DB) / 324 with DB (308 + 16 DB skips lifted);
# adds 5 new analytics_sink tests.
```

### Checkpoint ε

```
$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker_plugin_keyword_block
All checks passed!

$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_plugin_keyword_block/tests -q
9 passed in 0.10s

$ LLMTRACK_TEST_DATABASE_URL=... .venv/bin/python3.12 -m pytest -q
329 passed, 4 warnings in 30.49s
# No new tests in ε (rename + default-change only); full suite green.
```

### Checkpoint ζ

```
$ docker build -t llm-tracker-server:zeta .
exporting to image ... DONE 4.7s
naming to docker.io/library/llm-tracker-server:zeta done

$ docker run --rm --entrypoint python llm-tracker-server:zeta \
    -c "from importlib.metadata import entry_points; \
    print(sorted(ep.name for ep in \
    entry_points(group='llm_tracker.plugins')))"
['analytics_sink', 'keyword_block']

$ docker run -d -p 18081:8080 --name lts-zeta-smoke \
    llm-tracker-server:zeta
$ curl -sS http://localhost:18081/healthz
{"status":"ok","version":"0.0.1"}
$ docker stop lts-zeta-smoke
```

## What's left / known limits

- **Operator-run smoke** (instructions for the operator, not auto-runnable
  from this session):
  1. `fly deploy` to push the new image (release_command runs `alembic
     upgrade head`, advancing the stamp to `0007_plugin_analytics`).
  2. Verify both plugins loaded:
     `curl -H "X-LLM-Tracker-Token: <token>" \
      https://llm-tracker-server.fly.dev/admin/plugins`
     — expect `analytics_sink` and `keyword_block` in the list.
  3. Fire a real request through `claude-manage` (any small prompt).
  4. Confirm via Supabase MCP that exactly one row landed in
     `public.plugin_analytics` for the operator's org with non-NULL
     `model_served`, `input_tokens`, `output_tokens`, `stop_reason`,
     and a non-empty `response_json`.
- **ADR-#2 consent + data-handling**: now elevated in priority — the
  `analytics_sink` plugin stores the *full* request + response payloads.
  Currently the central server is **operator-only**; any external testing
  blocks on this ADR.
- Pre-SSE failure-path row write (ADR-0027 axis 2 impl) — deferred.
- Tool-use extraction (`tool_call_count > 0` on `exchanges` and
  `plugin_analytics`) — extractor parses text content only; flagged in
  `extractors/anthropic.py` docstring.

## Handoff

All six checkpoints landed:

```
α   f02f516   docs: ADR-0026 HookContext response accessors + ADR-0027 close-out policy
β   61c8aeb   server: Option B SSE extractor + HookContext response accessors
γ   49804f5   storage: migration 0007 plugin_analytics table
δ   b3f9ed2   agent: analytics_sink plugin (on_request_received + on_persisted)
ε   7741c13   agent: keyword_block plugin package (promoted from test harness)
ζ   854d4ee   infra: bundle analytics_sink + keyword_block in Docker image
```

Plus per-checkpoint docs commits (β `6d84b24`, γ `4d4ea9f`, plus this
final session-end commit). Next session: operator-run smoke on Fly
(see "What's left" above for the four-step recipe).
