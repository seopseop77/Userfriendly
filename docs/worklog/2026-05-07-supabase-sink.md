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

### Checkpoint 1 — ADRs and worklog kickoff (commit pending)

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

## Decisions

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

ADR-only checkpoint — no code changes, no tests run. Internal links
spot-checked:

- ADR-0015 references resolve: ADR-0006, ADR-0007, ADR-0012, plugins.md §8,
  design.md §6.2, this worklog, CLAUDE.md §10.
- ADR-0016 references resolve: ADR-0006, ADR-0007, ADR-0012,
  design.md §7, roadmap.md Phase 2, CLAUDE.md §10.
- STATUS.md "Active worklog" path matches this file's path.

Code checkpoints below (CP2 onward) will paste pytest + ruff output as
they land.

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
