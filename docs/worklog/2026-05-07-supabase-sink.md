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

### Checkpoint 4 — Supabase schema migration (2026-05-08, commit pending)

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

CP4 (Supabase schema): no repo tests — verification is
`mcp__supabase__list_tables` after each migration. After
`create_exchanges_table` the table appears with all 18 columns + 2
indices + table comment + PK on `exchange_id`. After
`enable_rls_on_exchanges` the same call returns `rls_enabled: true`
and the previous critical advisory is gone.

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

After CP1 commit, the next single step is **CP2: EgressClient SDK +
HostEgressClient + per-plugin wiring**. Files to touch:

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
