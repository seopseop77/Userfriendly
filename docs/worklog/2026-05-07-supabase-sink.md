# 2026-05-07 · Phase-2 reference plugin (supabase_sink) — early

**Author**: Claude Code
**Session trigger**: User: "이번엔 모델과 소통할 때 입력 prompt랑 그에 해당하는 모델의 output을 supabase에 전송하여 정리하는 plugin을 만들 수 있을까? egress 기능도 테스트해봐야 하니까. 대신 이번엔 어느 정도 유의미한 기능이니까 좀 탄탄하게, 실제 작동할 수 있는 plugin처럼 좀 제대로 만들어도 좋을 것 같아."
**Related docs**: ADR-0006 (egress policy), ADR-0007 (`supabase_sink` is the
named Phase-2 reference plugin), ADR-0012 (HookContext), ADR-0015 (egress
client SDK), ADR-0016 (user opt-in env knob), `docs/plugins.md §8`,
`docs/design.md §13.1`, `docs/roadmap.md` Phase 2

## Interpretation

User asked for a "real, working" plugin (vs. the previous two TEST-ONLY
plugins) that ships request prompt + model response to Supabase. They flagged
this would also exercise the egress stack end-to-end. They also signalled
that Phase 1c (`scope_guard`) needs more discussion and asked to do this
first instead.

This is the canonical Phase-2 reference plugin per ADR-0007 §1, brought
forward ahead of `roadmap.md`'s order. Three core surfaces are forced into
the same window:

- The promised-but-undelivered `ctx.egress.fetch(...)` (plugins.md §8 has
  said "arrives in Phase 1b" since Phase 1a; Phase 1b sealed without it).
- A way to lift Mode R's content ceiling to L3 so prompt/response text can
  actually leave the proxy (the real per-task consent UX is Phase-2 stretch
  per ADR-0006 §"Open questions").
- The plugin package itself.

User confirmed sequencing trade-off (Phase 1c skipped, Phase 2 partially
brought forward) explicitly in the planning chat. The egress client SDK is
a Phase-1b debt repayment, not a Phase-3 pull-forward.

The plan was reviewed by the critic agent and rejected for seven changes.
The three load-bearing ones are folded into the design before
implementation:

1. `EgressClient` is **per-plugin lifetime**, not per-exchange (so background
   flushers can call it). `ctx.egress` is a same-instance shortcut.
2. `LLMTRACK_USER_OPTED_IN` is a `PluginHost` startup-time field (mirrors
   `mode`), threaded into `begin_exchange` internally; the forwarder is not
   touched.
3. The plugin uses `on_response_complete` (not `on_persisted` as
   design.md §13.1 suggests) because it parses SSE itself and doesn't need
   the persisted DB row. Documented as a deliberate deviation.

The other four critic changes are accepted: drop the HTTPS-only manifest
hardening (out of scope per CLAUDE.md §2.3), correct the "PostgREST →
Edge Function = one-line change" claim to "client.py-scoped change", add
Mode L safety / `\r\n` boundary / image content block / `on_shutdown` race
tests.

## What was done

### Checkpoint 1 — ADRs and worklog kickoff (commit 8712183)

- Created `docs/decisions/0015-egress-client-sdk.md` — adds `EgressClient`
  Protocol + `EgressResponse` + `EgressDenied` to the SDK; specifies
  per-plugin lifetime; specifies `ctx.egress` and `BasePlugin.egress` as
  the same instance; specifies that the shared `httpx.AsyncClient` is
  closed during proxy `lifespan` exit *after* every plugin's
  `on_shutdown` so a plugin's flusher can still call `fetch`.
- Created `docs/decisions/0016-user-opt-in-env-knob.md` — adds
  `LLMTRACK_USER_OPTED_IN` (default False), held as a `PluginHost`
  startup-time field, threaded into every `HookContext`. Interim consent
  surface; real per-task UX deferred. Reversibility: high.
- Updated `docs/STATUS.md` — points active worklog at this file; refreshed
  "Where we paused" and "Next single step".

### Checkpoint 2 — EgressClient SDK + HostEgressClient + per-plugin wiring (commit f75a841)

- Created `packages/llm_tracker_sdk/src/llm_tracker_sdk/egress.py` —
  `EgressResponse` (frozen dataclass), `EgressDenied` (carries url +
  reason), `EgressClient` (Protocol with `fetch(url, *, method="POST",
  headers=None, body=None, timeout=30.0)`).
- Modified `packages/llm_tracker_sdk/src/llm_tracker_sdk/__init__.py` —
  exports `EgressClient`, `EgressDenied`, `EgressResponse`.
- Modified `packages/llm_tracker_sdk/src/llm_tracker_sdk/hook_context.py` —
  `HookContext.egress: EgressClient | None = None`.
- Modified `packages/llm_tracker_sdk/src/llm_tracker_sdk/plugin.py` —
  `BasePlugin.egress: EgressClient | None = None`. Populated by host at
  load time; background tasks hold this; `ctx.egress` is the same instance
  for in-hook ergonomics (ADR-0015).
- Created `packages/llm_tracker/src/llm_tracker/egress_guard/client.py` —
  `HostEgressClient` implements the SDK Protocol; bound to
  `(plugin_name, EgressGuard, httpx.AsyncClient)` at construction; calls
  `guard.check(plugin=self._plugin_name, url=url, capability="egress_http")`
  then routes through httpx; raises `EgressDenied` on guard denial.
- Modified `packages/llm_tracker/src/llm_tracker/plugin_host/host.py` —
  - `__init__` accepts `http_client: httpx.AsyncClient | None = None`
    (None preserves existing test paths that don't exercise egress).
  - In `load_plugins`, after the plugin instance is constructed and the
    manifest passes every load-time check, the host builds one
    `HostEgressClient` per plugin and assigns it to `plugin.egress`
    (only when both `egress_guard` and `http_client` are wired).
  - All six per-exchange dispatchers (`on_request_received`,
    `before_forward`, `on_upstream_response_start`, `on_response_chunk`,
    `on_response_complete`, `on_persisted`) now do
    `ctx.egress = plugin.egress` immediately before each plugin's hook
    dispatch, so `ctx.egress` and `self.egress` point at the same
    instance for the plugin currently in its hook (ADR-0015 §Decision-3).
- Modified `packages/llm_tracker/src/llm_tracker/proxy/app.py` lifespan —
  creates a shared `httpx.AsyncClient(timeout=None)` before host
  construction, passes it to `PluginHost(http_client=...)`, and closes
  it in a `try/finally` *after* `host.on_shutdown()` (so any plugin's
  shutdown-time flusher can still call `fetch`).
- Created `packages/llm_tracker/tests/test_egress_client.py` (4 tests) —
  happy path (guard allows → httpx invoked → `EgressResponse` round-trips
  + `egress_attempt` audit row); Mode L denial (`EgressDenied` raised,
  httpx never touched, `egress_blocked` audit row with reason
  `mode_L_denies_egress`); cross-plugin destination (client bound to
  `plugin_a` denied when targeting `plugin_b`'s allowlist entry; audit
  row attributes the attempt to `plugin_a`); default method = POST.
- Created `packages/llm_tracker/tests/test_egress_protocol.py` (5 tests) —
  `EgressResponse` is frozen; `EgressDenied` carries url + reason;
  Protocol `fetch` signature pinned (defaults: POST, None, None, 30.0);
  `BasePlugin.egress` defaults to None; `HookContext.egress` defaults
  to None.

### Checkpoint 3 — `LLMTRACK_USER_OPTED_IN` env + `PluginHost` field (commit dff7e3e)

- Modified `packages/llm_tracker/src/llm_tracker/config.py` —
  `Settings.user_opted_in: bool = False` (`LLMTRACK_USER_OPTED_IN`).
  pydantic-settings' default boolean coercion handles `1`/`true`/`yes`
  → True, everything else → False.
- Modified `packages/llm_tracker/src/llm_tracker/plugin_host/host.py`:
  - `PluginHost.__init__` accepts `user_opted_in: bool = False`,
    stored as `self._user_opted_in` (parallel to `self.mode`).
  - `begin_exchange` drops its `user_opted_in` parameter and reads
    `self._user_opted_in` instead — the forwarder no longer needs to
    know about consent (ADR-0016 §Plumbing).
  - `_ctx_for` fallback path also reads `self._user_opted_in` so the
    no-`begin_exchange` test path matches production behaviour.
  - Docstring on `begin_exchange` updated to point at ADR-0016 (was
    "wired by Phase 1c's user-consent flow").
- Modified `packages/llm_tracker/src/llm_tracker/proxy/app.py`
  lifespan — passes `user_opted_in=settings.user_opted_in` to
  `PluginHost`. The forwarder is untouched.
- Updated `packages/llm_tracker/tests/test_plugin_host.py`:
  - `test_user_opt_in_lifts_ceiling_in_mode_r` rewritten to construct
    the host with `user_opted_in=True` instead of passing the flag to
    `begin_exchange`.
  - New `test_user_opt_in_default_false_caps_mode_r_at_l1` pins the
    "off by default" axiom + the `_ctx_for` fallback path.
- Updated `packages/llm_tracker/tests/test_config.py` (+3 tests):
  default False; truthy env values (`1`/`true`/`True`/`yes`/`YES`)
  → True; falsy env values (`0`/`false`/`False`/`no`/`NO`) → False.

### Checkpoint 4 — Supabase schema migration (2026-05-08, commit a3b5dff)

Schema-only checkpoint — no repo code change. Two migrations applied
to the operator's Supabase project
(`https://qdcixbwwlsnkekabavmj.supabase.co`) via the Supabase MCP
`apply_migration` tool:

- **`create_exchanges_table`** — `public.exchanges` PK
  `exchange_id`; `session_id, ts_started_ms (bigint epoch ms),
  ts_inserted (timestamptz default now()), mode, endpoint,
  model_requested, model_served, stop_reason, input_tokens,
  output_tokens, cache_creation_input_tokens,
  cache_read_input_tokens, request_text, response_text, raw_request
  jsonb, raw_response jsonb, source`. Indices: `(session_id,
  ts_started_ms)` and `ts_inserted`. Table comment cites ADR-0007 +
  this worklog.
- **`enable_rls_on_exchanges`** — `alter table public.exchanges
  enable row level security`. No policies. Reason: the supabase_sink
  plugin authenticates with `service_role`, which bypasses RLS at
  the Postgres level — plugin writes are unaffected. The `anon` /
  `authenticated` roles are now locked out, which protects the
  prompt + response payload if the anon (publishable) key ever
  leaks. The Supabase advisory `rls_disabled` (priority: critical)
  surfaced after migration #1 and was the trigger for migration #2.

Verified via `mcp__supabase__list_tables` after each migration:
table created with all columns/indices on the first call;
`rls_enabled: true` after the second call (advisory cleared).

The plugin package (CP5) will check in a `schema.sql` next to the
plugin source so the schema lives in the repo, not just on the
remote.

### Checkpoint 5 — supabase_sink package skeleton + parser + unit tests (2026-05-08, commit 9088825)

- Created `packages/llm_tracker_plugin_supabase_sink/pyproject.toml`
  — workspace member, hatchling build, depends on `llm-tracker-sdk`,
  registers the entry point `supabase_sink =
  "llm_tracker_plugin_supabase_sink:SupabaseSinkPlugin"`.
- Created
  `packages/llm_tracker_plugin_supabase_sink/src/llm_tracker_plugin_supabase_sink/plugin.toml`
  — manifest. Hooks: `on_init`, `on_response_chunk`,
  `on_response_complete`, `on_shutdown` (deliberate deviation from
  design.md §13.1 which suggested `on_persisted` — see Decisions).
  Capabilities: `read_request_metadata`, `read_request_content`,
  `read_response_metadata`, `read_response_content`, `egress_http`.
  `egress_destinations` is a single PostgREST URL. `allowed_modes =
  ["R"]`. `db_namespace = "supabase_sink"`. (Manifest signing in
  CP8.)
- Created
  `packages/llm_tracker_plugin_supabase_sink/src/llm_tracker_plugin_supabase_sink/schema.sql`
  — byte-exact CP4 DDL (`create table` + indices + table comment +
  `alter table … enable row level security`) checked into the repo
  for reproducibility.
- Created
  `packages/llm_tracker_plugin_supabase_sink/src/llm_tracker_plugin_supabase_sink/parser.py`:
  - `ResponseAssembler` — Anthropic SSE accumulator. Buffers raw
    bytes, parses event/data blocks, tracks `model`, `stop_reason`,
    4 usage fields (max-merge — `message_delta.output_tokens` is
    cumulative final). `text_delta` events accumulate into per-index
    blocks; `response_text` joins text-only blocks with `\\n\\n` in
    index order. Handles `\\n\\n` *and* `\\r\\n\\r\\n` event
    terminators (some HTTP stacks emit CRLF). Bad UTF-8 / invalid
    JSON in any block drops only that block.
  - `extract_request_text(body)` — decodes the cached request body,
    renders `system` + `messages[].content` into a labelled
    human-readable string. Image blocks → literal `[image]` (never
    ship base64 to Supabase). Tool blocks render compactly:
    `[tool_use name(input_json)]`, `[tool_result tool_use_id]
    content`. Returns `(text, raw_dict)`; failure modes (empty,
    non-UTF-8, non-JSON, top-level non-dict) return `("", None)`.
- Created
  `packages/llm_tracker_plugin_supabase_sink/src/llm_tracker_plugin_supabase_sink/__init__.py`
  — exports `ResponseAssembler`, `extract_request_text`, and a
  *placeholder* `SupabaseSinkPlugin` class (just `name =
  "supabase_sink"` over `BasePlugin`). The full lifecycle/queue/
  flusher/client wiring lands in CP6; the placeholder is enough for
  the entry point to resolve.
- Created `packages/llm_tracker_plugin_supabase_sink/tests/test_parser.py`
  with **26 unit tests** covering both surfaces:
  - SSE: in-order text deltas; multi-block `\\n\\n` join; non-text
    blocks excluded; per-byte chunk fragmentation; `\\r\\n\\r\\n`
    terminators; mixed LF/CRLF; usage max across `message_start` +
    `message_delta`; unknown event types skipped; invalid JSON
    dropped; non-UTF-8 dropped; `raw_response_summary` shape.
  - Request: string content; list of text blocks; image →
    placeholder + base64 absent from rendered text; tool_use with
    rendered input; tool_result with string content; tool_result
    with list content; top-level system string; top-level system
    block list; invalid JSON; empty; missing `messages`; non-dict
    message entries; non-UTF-8 body; top-level non-object; unknown
    block types skipped (forward-compat).
- Modified `pyproject.toml` (workspace root) — added
  `packages/llm_tracker_plugin_supabase_sink/tests` to
  `[tool.pytest.ini_options].testpaths`.
- Refreshed `uv.lock` for the new workspace member.

### Checkpoint 6 — `client.py` + plugin lifecycle + queue/flusher + tests (2026-05-08, commit 6ab979c)

- Created
  `packages/llm_tracker_plugin_supabase_sink/src/llm_tracker_plugin_supabase_sink/client.py`:
  - `ExchangeRecord` (frozen dataclass) mirrors the CP4 schema 1:1; a
    `to_postgrest_row()` helper turns it into the JSON-serialisable
    dict that ships in the request body.
  - `SubmitOutcome` enum: `OK` (200/201), `IDEMPOTENT_SKIP` (409),
    `RETRY` (5xx), `TERMINAL_FAILURE` (other 4xx + `EgressDenied`).
    Pinned by parametrised tests.
  - `SupabaseSinkClient(url, headers_factory, egress)` — vendor
    coupling lives only here. Posts a single-row JSON array (PostgREST
    accepts both shapes; array form means a future batch-of-N variant
    is a one-line change). Headers: `apikey` + `Authorization: Bearer
    …` from the factory + `Content-Type: application/json` + `Prefer:
    resolution=ignore-duplicates`. Catches `EgressDenied` and maps it
    to `TERMINAL_FAILURE` (the guard already wrote the
    `egress_blocked` audit row).
- Overwrote
  `packages/llm_tracker_plugin_supabase_sink/src/llm_tracker_plugin_supabase_sink/__init__.py`
  — full `SupabaseSinkPlugin`:
  - `on_init` builds a `SupabaseSinkClient` from
    `LLMTRACK_PLUGIN_SUPABASE_SINK_URL` /
    `LLMTRACK_PLUGIN_SUPABASE_SINK_KEY` (or accepts a
    test-injected `client=`); starts the background flusher task. If
    env is missing or `self.egress` was not wired by the host, the
    plugin disables itself and logs a structlog warning instead of
    raising.
  - `on_response_chunk` no-ops unless `ctx.user_opted_in` (consent
    gate). On first chunk, captures `(session_id, mode,
    ts_started_ms=now, request_text+raw_request via
    extract_request_text(ctx._raw_request_body))` and a fresh
    `ResponseAssembler`. Subsequent chunks feed the assembler.
  - `on_response_complete` builds an `ExchangeRecord` from the
    captured state + the assembler's outputs and enqueues it.
  - Background flusher (`_collect_batch` + `_flush`): batches up to
    `batch_size` records or until `batch_interval_s` elapses (whichever
    first); per-record exp-backoff retry up to `max_attempts` (default
    3) on `RETRY`; drops + structlog-warns on `TERMINAL_FAILURE` or
    max-attempts-exceeded.
  - `on_shutdown` puts a `None` sentinel and awaits the flusher so
    queued records drain before exit.
  - `headers_factory` is a closure that re-reads `KEY_ENV` *each call*
    — the service_role key is never stored as a string attribute on
    the client (CLAUDE.md §7 + critic recommendation).
  - Plugin's tunables (`batch_size`, `batch_interval_s`,
    `max_attempts`, `backoff_base_s`, `sleep`) are constructor args
    so tests run fast (sleep stub) and exercise small-batch /
    aggressive-retry shapes.
- Created
  `packages/llm_tracker_plugin_supabase_sink/tests/test_client.py`
  (12 tests): parametrised status-code → `SubmitOutcome` mapping (10
  rows: 200/201/409/500/502/503/400/401/403/404), `EgressDenied` →
  `TERMINAL_FAILURE`, URL/header construction, JSON-array body shape,
  per-call `headers_factory` invocation (no caching), null-optional
  fields round-trip.
- Created
  `packages/llm_tracker_plugin_supabase_sink/tests/test_plugin.py`
  (14 tests): full chunk → submit pipeline; opted-out no-op;
  batch-size threshold flushes early; retry-then-succeed records
  twice (verify retry path); terminal failure drops without retry;
  max-attempts-exceeded drop; on_shutdown drains; `on_init` disables
  on missing env; `on_init` disables on no-egress; empty
  `on_response_complete` (Block/Abort path); two interleaved
  exchanges stay isolated.
- Modified `packages/llm_tracker_plugin_supabase_sink/pyproject.toml`
  — added `structlog` to `dependencies` (warnings on plugin-side
  drops). `httpx` is *not* a plugin dependency — egress is solely
  through `self.egress.fetch(...)`, the SDK Protocol.

### Checkpoint 7 — `on_shutdown` timeout extension (2026-05-08, commit 4294d10)

Critic-flagged in the original plan: `HOOK_TIMEOUT = 5.0 s` covers
*every* hook including `on_shutdown`, but a sink plugin's drain
(queue depth N + per-record exp-backoff retry) can legitimately
exceed that. Without a fix, supabase_sink would silently drop
records and audit-log a misleading `plugin_fault timeout`.

- Modified `packages/llm_tracker/src/llm_tracker/plugin_host/host.py`:
  - New constant `SHUTDOWN_HOOK_TIMEOUT = 30.0` alongside the
    existing `HOOK_TIMEOUT = 5.0`. Comment cites the sink-drain use
    case.
  - `_call` gains a keyword-only `timeout: float = HOOK_TIMEOUT`
    parameter — backward-compatible default for the five
    per-exchange dispatchers.
  - `on_shutdown` dispatcher passes `timeout=SHUTDOWN_HOOK_TIMEOUT`
    explicitly per plugin.
- Modified `packages/llm_tracker/tests/test_plugin_host.py` (+2
  tests):
  - `test_on_shutdown_uses_longer_timeout_than_per_exchange_hooks` —
    monkeypatches `HOOK_TIMEOUT=0.05` + `SHUTDOWN_HOOK_TIMEOUT=1.0`,
    runs a `_SlowShutdownPlugin(sleep=0.2)` (between the two
    budgets), pins that the plugin completes and *no* fault row is
    written.
  - `test_on_shutdown_still_faults_past_shutdown_timeout` — pairs
    with the above. Past the longer budget the dispatcher still
    cuts the plugin off so a misbehaving plugin can't hold the
    proxy hostage. `plugin_fault` audit row fires.

### Checkpoint 8 — integration test + manifest signing (2026-05-08, commit f420000)

- Signed `packages/llm_tracker_plugin_supabase_sink/src/llm_tracker_plugin_supabase_sink/plugin.toml.sig`
  via the existing CLI:
  ```
  $ .venv/bin/llm-tracker sign-plugin packages/llm_tracker_plugin_supabase_sink --signer minseop
  Wrote .../plugin.toml.sig
  ```
  Verifies against the bundled `trust/keys.toml` (which already
  contains the `minseop` public key). The signed manifest is what
  the plugin host enforces at load time per ADR-0008.
- Created
  `packages/llm_tracker_plugin_supabase_sink/tests/test_e2e.py`
  (3 integration tests). Wires `PluginHost` + `EgressGuard` +
  `HostEgressClient` + the live `SupabaseSinkPlugin` against a
  stubbed Anthropic upstream (SSE chunks fed straight into the
  host's `on_response_chunk` dispatcher) and a stubbed Supabase
  upstream (`httpx.MockTransport`). Pins three end-to-end shapes:
  - **Happy path** (Mode R + opted_in): a single POST hits the
    PostgREST URL with the expected `apikey` / `Authorization` /
    `Content-Type: application/json` / `Prefer:
    resolution=ignore-duplicates` headers, body is a JSON array of
    one row containing the right `exchange_id`, `mode`, `endpoint`,
    `source`, `model_*`, usage, `request_text`, `response_text`,
    `raw_request`, `raw_response`. Audit log shows
    `egress_attempt outcome=ok plugin=supabase_sink destination=…`.
  - **Allowlist mismatch**: env points at the legitimate URL but the
    plugin's manifest declares a different `egress_destinations`
    entry; EgressGuard denies, no POST hits the http transport,
    audit log shows ≥1 `egress_blocked` row with
    `reason=destination_not_in_allowlist`. (≥1 because the flusher's
    retry loop calls `submit` up to `max_attempts` and each call
    audits a denial.)
  - **Mode L safety**: in Mode L the `egress_http` capability is
    denied at *load time*, so the plugin never appears in
    `loaded_plugins()` and a `capability_denied` audit row fires.
    `egress_attempt` count stays at 0 even though we drive a fake
    exchange — the plugin literally cannot reach the network.
- The integration test uses the same monkey-patch pattern as
  `test_load_plugins_registers_manifest_with_egress_guard`
  (`entry_points` stub + `_find_manifest` override + verifier
  bypass) to drive *only* supabase_sink without pulling in the
  workspace's other entry-points (hello_world, token_counter,
  keyword_block).

### Side-quest — `.env` support for the proxy (2026-05-08, commit f2f53b7)

User flagged that re-exporting `LLMTRACK_PLUGIN_SUPABASE_SINK_*`
each shell session is annoying before CP9. Tiny operator-UX
addition.

- Modified `packages/llm_tracker/pyproject.toml` — moved
  `python-dotenv` (already a transitive of `pydantic-settings`) into
  the explicit `dependencies` list so we don't break if upstream
  drops it.
- Modified `packages/llm_tracker/src/llm_tracker/proxy/app.py` —
  `lifespan` calls `load_dotenv(override=False)` *before*
  `Settings()` so `.env` populates `os.environ`. Both pydantic-
  settings and the plugin's direct `os.environ.get(...)` then read
  the same source. `override=False` keeps shell exports
  authoritative — `.env` is for convenience, not for overriding a
  deliberately-set value. No-op when `.env` is absent.
- Replaced `.env.example` (was Phase-0-pre-stale, referenced env
  vars that no longer exist like `LLMTRACK_HOST`,
  `LLMTRACK_UPSTREAM_BASE_URL`, `LLMTRACK_CONTENT_LEVEL`,
  `LLMTRACK_DB_PATH`, `LLMTRACK_INGEST_*`, `LLMTRACK_LOG_LEVEL`)
  with the current `Settings` surface (`LLMTRACK_MODE`,
  `LLMTRACK_USER_OPTED_IN`, `LLMTRACK_PROXY_HOST`,
  `LLMTRACK_PROXY_PORT`, `LLMTRACK_DB_URL`,
  `LLMTRACK_PLUGINS_DISABLED`) plus the supabase_sink env block
  (`LLMTRACK_PLUGIN_SUPABASE_SINK_URL` / `_KEY`). `.env.example`
  is committable; `.env` is already in `.gitignore`.
- No new tests — `load_dotenv` is upstream-tested; the wiring is a
  one-line lifespan addition. Suite still 259 passed; ruff clean.

### Checkpoint 9 — manual e2e against the real Supabase project (2026-05-08, commit pending)

Three safety paths verified against real Anthropic + real Supabase
traffic. End of the supabase_sink workstream.

**Path 1 — Happy path** (Mode R + opted_in + correct manifest)

User filled `.env`, ran `claude-manage --print …` a few times.
Result: 7 rows in `public.exchanges`, all `mode=R`, all
`source=supabase_sink/0.1.0`. Spot-checks via
`mcp__supabase__execute_sql`:

- `model_requested` matches the request's `model` field
  (`claude-opus-4-7`, `claude-haiku-4-5-20251001`).
- `model_served` matches *when SSE arrived* — see Observation
  below for the one row where it's NULL.
- `request_text` is the rendered `[role]\n…` shape from
  `extract_request_text`; `response_text` is the assembled text
  delta join. `request_text` lengths 60–60k chars confirm system
  prompts and tool_use round-trip; image bodies (if any) would
  show up as `[image]` placeholders.
- Usage / cache_* token columns populated except in error rows.
- 7 matching `egress_attempt outcome=ok` rows in the local
  `audit_log`, each `plugin=supabase_sink destination=<env URL>`.

**Observation — one row with `model_served=null`** (`exchange_id
01KR1KQ9YBEGSDW6VQ1FCNQ5EP`, `request_text="[user]\nquota"`).
Cause: `ResponseAssembler` never saw a `message_start` SSE event
for this exchange, so `model`/`stop_reason`/`usage` stayed at
their initial values. Most likely an Anthropic HTTP error response
(rate-limit / quota / 4xx) that returned a JSON error body
*instead of* an SSE stream — our parser is SSE-only, so the
event boundary `\n\n` never fires, the assembler ends up with 0
blocks, and `on_response_complete` enqueues a sparsely-populated
record. Intentional behaviour: the row exists for forensics and
the NULLs are honest about what we couldn't observe. v0.2 could
add an `error_status` column or stash the raw error body in
`raw_response.error`; out of scope for v0.1.

**Path 2 — Mode L safety** (accidentally — but still valuable)

User's `.env` briefly reverted to `LLMTRACK_MODE=L` between Path 1
and Path 3. Result: a single audit row `capability_denied
plugin=supabase_sink detail_json={"mode": "L", "denied":
["egress_http"]}` at proxy startup. The plugin never reached the
hook dispatch loop; zero new Supabase rows; `claude` response
flowed through the proxy normally. This is the production
equivalent of the
`test_e2e_mode_l_rejects_plugin_at_load_time` integration test
from CP8.

**Path 3 — Allowlist mismatch** (the original CP9 negative-path
intent)

Procedure:

1. Edited the manifest's `egress_destinations` to
   `["https://wrong-host.invalid/rest/v1/exchanges"]` and
   re-signed with `llm-tracker sign-plugin … --signer minseop`.
2. User restored `LLMTRACK_MODE=R` in `.env` and ran
   `claude-manage --print "negative test 2"`.
3. Verification (this document's author, via the supabase MCP +
   the local `audit_log`):

```
$ mcp supabase execute_sql "select count(*), max(ts_inserted) from public.exchanges"
[{"total": 7, "latest": "2026-05-07 16:18:38.945705+00"}]   # unchanged
```

```
audit_log | most-recent run window:
  plugin_loaded: 4   (incl. supabase_sink — manifest sig verified, capabilities allowed in Mode R)
  egress_blocked: 4  (4 attempts: 1 record × max_attempts=3 + 1 partial retry from a second exchange)
  proxy_started/_stopped: 1 / 1
  hook_invoked: 20

egress_blocked detail_json (all 4 rows):
  plugin=supabase_sink
  capability=egress_http
  destination=https://qdcixbwwlsnkekabavmj.supabase.co/rest/v1/exchanges  ← env URL the plugin tried
  outcome=denied
  detail_json={"mode": "R", "reason": "destination_not_in_allowlist"}
```

So the plugin loaded (manifest sig verified, capabilities allowed
in Mode R), tried to call out to the env URL, EgressGuard
compared it against the manifest's allowlist (`wrong-host.invalid`)
and denied each attempt with the right reason. Zero rows landed
in Supabase. The `claude` response still flowed through the proxy
normally — the operator-facing impact is "you don't get any
Supabase upload" rather than "Claude is broken".

**Cleanup**

- Restored `egress_destinations` to the production URL and
  re-signed. ed25519 signatures are deterministic over
  `(key, message)`, so the regenerated `plugin.toml.sig` is
  byte-identical to the file committed in CP8 — `git status` is
  clean.
- Suite re-run: `259 passed`. No regressions.

**Phase-2-partial wrap-up**

`llm_tracker_plugin_supabase_sink` workstream closes here. ADR-0007's
named reference plugin is now operational against a real Supabase
project. Phase 1c (`scope_guard`), the rest of Phase 2
(`llm_tracker_server` routes, full per-task consent UX,
`drift_metrics` contributor plugin), and the Phase-1b loose ends
listed in STATUS.md remain on the deck.

## Decisions

- **RLS enabled on `public.exchanges` with no policies** (CP4,
  2026-05-08). service_role bypasses RLS at the Postgres level so
  the supabase_sink plugin (which uses the service_role key) is
  unaffected; anon and authenticated roles are locked out, which
  protects the prompt + response payload if the anon key ever
  leaks. Trigger: critical Supabase advisory `rls_disabled` after
  the initial table migration. User-confirmed in chat before
  applying. Lower-effort alternatives considered (do nothing /
  explicit policy) and rejected; "RLS on, no policies" is the
  smallest patch that closes the advisory without touching the
  plugin's auth path.
- **`EgressClient` lifetime is per-plugin, not per-exchange** (ADR-0015).
  Critic-flagged: a per-exchange API would break batched/retry flushers
  (the canonical Mode-R plugin pattern). The plugin's audit-log identity
  is baked into the client at construction time, so a plugin literally
  cannot mis-attribute an egress.
- **`ctx.egress` and `BasePlugin.egress` reference the same instance**.
  Plugins use whichever is ergonomic in context; the type-system answer
  is "they are the same object". Replacing the field at runtime is
  out-of-contract (ADR-0015 §Decision-3 con).
- **Process-wide opt-in env, not per-task UX, for now** (ADR-0016).
  Smallest surface that unblocks supabase_sink. Default False keeps
  ADR-0006's "off by default" axiom intact.
- **Skip Phase 1c explicitly, do Phase-2-supabase_sink-only first** —
  user-confirmed in chat. Phase 2's *other* line items (`llm_tracker_server`
  routes, `drift_metrics` contributor plugin, full per-task consent UX)
  remain untouched; this is a partial Phase-2 deliverable.
- **A3 from the original plan dropped** — the "egress_destinations must be
  HTTPS" manifest validator was added by Claude Code in the planning pass,
  not requested by the user; out of scope per CLAUDE.md §2.3 (surgical
  changes). Defer as a separate hardening checkpoint if/when needed.

## Verification

CP1 (ADRs only) — internal links spot-checked: ADR-0015 (→ ADR-0006,
0007, 0012, plugins.md §8, design.md §6.2, this worklog, CLAUDE.md §10),
ADR-0016 (→ ADR-0006, 0007, 0012, design.md §7, roadmap.md Phase 2,
CLAUDE.md §10), STATUS.md "Active worklog" path matches this file.

CP2 (EgressClient + wiring):

```
$ .venv/bin/python3.12 -m pytest -q
............................................................   [ 36%]
............................................................   [ 72%]
......................................................          [100%]
198 passed, 4 warnings in 1.38s
```

Test count went from 189 → 198 (+9 new: 4 in `test_egress_client.py`,
5 in `test_egress_protocol.py`). The pre-existing
`test_cli_manage` deprecation warnings are untouched (carried over from
the `claude-manage` work, see `docs/worklog/2026-05-07-claude-manage.md`).

CP3 (user_opted_in env + host field):

```
$ .venv/bin/python3.12 -m pytest -q
............................................................   [ 35%]
............................................................   [ 71%]
..........................................................     [100%]
202 passed, 4 warnings in 1.33s
```

Test count went 198 → 202 (+4 new: 3 in `test_config.py` for the env
coercion paths, 1 in `test_plugin_host.py` for the default-False
fallback through `_ctx_for`). The existing
`test_user_opt_in_lifts_ceiling_in_mode_r` was rewritten in-place to
match the ADR-0016 plumbing and still passes.

Ruff format + check on every changed file (CP3): 1 file reformatted
(`test_config.py`), 4 left unchanged, all checks passed.

CP9 (manual e2e against real Supabase): see the dedicated CP9 entry
in "What was done" above for the structured walk through Paths 1/2/3.
End-of-CP9 state: 7 rows in `public.exchanges` from Path 1, 0
new rows from Paths 2+3, audit log shows `egress_attempt: 7`,
`egress_blocked: 4`, `capability_denied: 1` for the run window.
`pytest -q`: `259 passed`.

CP4 (Supabase schema): no repo tests — verification is
`mcp__supabase__list_tables` after each migration. After
`create_exchanges_table` the table appears with all 18 columns + 2
indices + table comment + PK on `exchange_id`. After
`enable_rls_on_exchanges` the same call returns `rls_enabled: true`
and the previous critical advisory is gone.

CP5 (supabase_sink package + parser):

```
$ .venv/bin/python3.12 -m pytest -q
............................................................   [ 31%]
............................................................   [ 63%]
............................................................   [ 94%]
.............                                                    [100%]
228 passed, 4 warnings in 1.34s
```

Test count went 202 → 228 (+26 new — all in
`packages/llm_tracker_plugin_supabase_sink/tests/test_parser.py`).
Targeted run on the new package alone: `26 passed in 0.06s`.

Ruff format + check: 2 files reformatted (parser.py, tests),
1 file left unchanged. Initial run flagged a single I001
(import-sort) in `test_parser.py`, autofixed by `ruff check --fix`.
Final `ruff check packages/llm_tracker_plugin_supabase_sink`: all
checks passed.

CP6 (client + plugin lifecycle + queue/flusher):

```
$ .venv/bin/python3.12 -m pytest -q
............................................................   [ 23%]
............................................................   [ 47%]
............................................................   [ 70%]
............................................................   [ 94%]
..............                                                   [100%]
254 passed, 4 warnings in 1.74s
```

Test count went 228 → 254 (+26 new: 12 in `test_client.py`, 14 in
`test_plugin.py`). Targeted run on the supabase_sink package alone:
`52 passed in 0.53s` (parser + client + plugin all green).

Ruff format + check: 3 files reformatted, 3 unchanged. Initial
check flagged `UP041` (`asyncio.TimeoutError` aliases builtin
`TimeoutError` in 3.11+), `I001` import-sort in `test_plugin.py`,
and `F401` unused `typing.Any` import — all autofixed by
`ruff check --fix`. Final check: clean.

CP7 (`on_shutdown` timeout extension):

```
$ .venv/bin/python3.12 -m pytest -q
............................................................   [ 23%]
............................................................   [ 46%]
............................................................   [ 70%]
............................................................   [ 93%]
................                                                 [100%]
256 passed, 4 warnings in 7.00s
```

Test count went 254 → 256 (+2 — both pinning the new
`SHUTDOWN_HOOK_TIMEOUT` semantics). The 7-second wall time is
expected: the second test deliberately exercises the past-budget
path with `SHUTDOWN_HOOK_TIMEOUT=0.1` and a `sleep=0.5`, so the
dispatcher waits the full 0.5 s in real time to verify the cutoff.
Ruff: 1 file reformatted, all checks passed.

CP8 (integration test + manifest signing):

```
$ .venv/bin/python3.12 -m pytest -q
............................................................   [ 23%]
............................................................   [ 46%]
............................................................   [ 69%]
............................................................   [ 92%]
...................                                              [100%]
259 passed, 4 warnings in 7.10s
```

Test count went 256 → 259 (+3 — all in `test_e2e.py`).
Targeted run on the supabase_sink package: `55 passed in 0.66s`
(parser 26 + client 12 + plugin 14 + e2e 3). Ruff clean on the
new file.

Manifest signature verification verified by inspection: the
bundled `packages/llm_tracker/src/llm_tracker/trust/keys.toml`
contains the `minseop` public key, the new
`plugin.toml.sig` is signed by that key, and the verifier path
through `verify_manifest_signature` is already covered by the
core `test_signing.py` suite.

Ruff format + check on every changed file (CP2):

```
$ .venv/bin/python3.12 -m ruff format \
    packages/llm_tracker_sdk/src/llm_tracker_sdk/egress.py \
    packages/llm_tracker_sdk/src/llm_tracker_sdk/__init__.py \
    packages/llm_tracker_sdk/src/llm_tracker_sdk/hook_context.py \
    packages/llm_tracker_sdk/src/llm_tracker_sdk/plugin.py \
    packages/llm_tracker/src/llm_tracker/egress_guard/client.py \
    packages/llm_tracker/src/llm_tracker/plugin_host/host.py \
    packages/llm_tracker/src/llm_tracker/proxy/app.py \
    packages/llm_tracker/tests/test_egress_client.py \
    packages/llm_tracker/tests/test_egress_protocol.py
2 files reformatted, 7 files left unchanged

$ .venv/bin/python3.12 -m ruff check  <same files>
All checks passed!
```

## What's left / known limits

Plan calls for 8 more checkpoints (numbering continues from CP1 above):

- **CP2**: `EgressClient` SDK module + `HostEgressClient` core impl;
  PluginHost wires per-plugin instances; tests for deny / allow / cross-
  plugin destination.
- **CP3**: `LLMTRACK_USER_OPTED_IN` env + `PluginHost.user_opted_in`
  field; threaded into `begin_exchange`; tests.
- **CP4**: Supabase migration (`public.exchanges` table) via
  `mcp__supabase__apply_migration`. Schema-only, no code.
- **CP5**: `packages/llm_tracker_plugin_supabase_sink/` skeleton +
  `parser.py` (SSE response_text + RequestExtractor that handles
  `messages[]` content variants — text, tool_result, image-as-placeholder).
  Unit tests for `\n\n` *and* `\r\n\r\n` chunk boundaries.
- **CP6**: `client.py` (vendor coupling lives only here, takes
  `(url, headers_factory)` so PostgREST → Edge Function later is a
  client-scoped change), plugin `__init__.py` (queue + background
  flusher, exp-backoff retry, drop-after-N audit warning),
  `PluginHarness`-driven unit tests.
- **CP7**: `PluginHost.on_shutdown` gets a longer dedicated timeout (30 s
  vs. the 5 s `HOOK_TIMEOUT` for per-exchange hooks) so the flusher can
  drain. Test: a queue larger than the per-exchange timeout still
  drains on shutdown.
- **CP8**: integration test (Mode R + opted_in proxy, fake Anthropic
  upstream, mocked Supabase httpx — happy + egress_blocked negative +
  Mode L safety); manifest signed by `minseop`.
- **CP9**: manual e2e against the real Supabase project
  (`https://qdcixbwwlsnkekabavmj.supabase.co`); STATUS.md flips to
  "Phase 2 partial: supabase_sink shipped".

Not in scope for v0.1 (deferred to v0.2 / future ADRs):

- Persistent local outbox (sidecar SQLite) for survive-restart guarantees.
- Schema migration tooling on the plugin side.
- Multi-destination fanout.
- Real per-task consent UX (defers ADR-0006 §Open questions §3).
- Manifest HTTPS-only validator (originally proposed; dropped per
  Decisions above).
- `llm_tracker_server` routes / repositories (Phase 2 remainder).

## Handoff

**Workstream closed.** All 9 checkpoints + the `.env` side-quest
shipped as 9 commits (`8712183`, `f75a841`, `dff7e3e`, `a3b5dff`,
`9088825`, `6ab979c`, `4294d10`, `f420000`, `f2f53b7`) plus the
final CP9 doc-only commit. `llm_tracker_plugin_supabase_sink` is
operational against the operator's Supabase project and the
three-axis safety model (Mode L / consent / allowlist) is verified
against real traffic.

The next session's "Next single step" should rotate to either
Phase 1c (`scope_guard`) — which the user explicitly deferred at
the start of this workstream and which now needs its own planning
pass — or one of the Phase-1b loose ends still tracked in STATUS.md
("end_exchange cleanup in the forwarder", per-level shape
refinement of `ctx.request_text()`, manifest `min_content_level`,
response-side ctx accessors). STATUS.md has been refreshed
accordingly.

For *historical* reference, the original CP1 handoff that started
this workstream pointed at **CP2: EgressClient SDK +
HostEgressClient + per-plugin wiring**. Files touched:

- `packages/llm_tracker_sdk/src/llm_tracker_sdk/egress.py` (new)
- `packages/llm_tracker_sdk/src/llm_tracker_sdk/__init__.py` (export
  `EgressClient`, `EgressResponse`, `EgressDenied`)
- `packages/llm_tracker_sdk/src/llm_tracker_sdk/hook_context.py`
  (add `egress: EgressClient | None` field)
- `packages/llm_tracker_sdk/src/llm_tracker_sdk/plugin.py` (add
  `egress: EgressClient | None = None` to `BasePlugin`)
- `packages/llm_tracker/src/llm_tracker/egress_guard/client.py` (new —
  `HostEgressClient`)
- `packages/llm_tracker/src/llm_tracker/plugin_host/host.py` (host
  builds and attaches one `HostEgressClient` per loaded plugin; reuses
  proxy's shared `httpx.AsyncClient` from
  `proxy/forwarder.py:24-31`).
- Tests: `packages/llm_tracker/tests/test_egress_client.py` (new —
  deny path, happy path, cross-plugin destination block);
  `packages/llm_tracker_sdk/tests/test_egress_protocol.py` (new — type
  checks).

ADR-0015 §Lifecycle is the spec; the executor should not invent
lifecycle details.

## Suggestions (untouched)

- **Manifest HTTPS-only validator** (dropped from CP1's plan). Worth a
  small standalone hardening checkpoint after Phase 2 settles. Add a
  carve-out for `127.0.0.1` / `localhost` so local Supabase dev still
  works.
- **`end_exchange` cleanup in the forwarder**. Still a STATUS.md "Phase
  1b loose end". This work doesn't depend on it (per-plugin egress
  client lifetime sidesteps it), but the leak in `_exchange_contexts`
  is real and should land before any future ctx.* accessors that grow
  meaningful state.
- **`on_persisted` ordering for sinks that DO want the persisted DB
  row**. Once the Phase-2 Extractor lands and writes assembled
  request/response back into the `Exchange` row, a future sink could
  read from there instead of accumulating SSE in-plugin. Not urgent;
  the SSE accumulation pattern is fine for v0.1.
- **Audit-log signal for `(mode, user_opted_in)`**. ADR-0016 §Open
  questions calls this out — `proxy_started` rows should record the
  consent stance so audit forensics can answer "what was the consent
  posture during this exchange". Small follow-up.
