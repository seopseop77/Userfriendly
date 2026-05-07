# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-08 (CP5 — supabase_sink package skeleton + parser + 26 unit tests)
**Updated by**: Claude Code

## Current phase

- **Phase**: **Phase-2 partial — supabase_sink reference plugin (early)**. Phase 1c (`scope_guard`) explicitly deferred per user. The egress client SDK is a Phase-1b debt repayment forced by this work; the consent env knob is the smallest surface that lifts Mode R's ceiling without bundling the full Phase-2 consent UX (ADR-0016).
- **Active task**: 9-checkpoint plan for `llm_tracker_plugin_supabase_sink`. CP1–CP5 done (ADRs, EgressClient SDK, opt-in env, Supabase schema, package skeleton + parser). CP6 (client + lifecycle + queue/flusher) is next.

## Active worklog

`docs/worklog/2026-05-07-supabase-sink.md`

## Recent commits

```
<CP5>     supabase-sink: package skeleton + parser + tests
a3b5dff   supabase-sink: schema migrated + RLS enabled
dff7e3e   config: LLMTRACK_USER_OPTED_IN env + PluginHost field
f75a841   egress: EgressClient SDK + per-plugin wiring
8712183   docs: ADR-0015/0016 + supabase-sink kickoff
```

## Where we paused

**Phase-2 reference plugin (`supabase_sink`) work kicked off; CP1
(ADRs) about to land.** User asked for a "real, working" plugin that
ships request prompt + model response to a Supabase Postgres,
explicitly to also exercise the egress stack end-to-end. Plan was
critic-reviewed and folded its three load-bearing changes back into
the design before commit:

- **ADR-0015** (`docs/decisions/0015-egress-client-sdk.md`) — adds
  `EgressClient` Protocol + `EgressResponse` + `EgressDenied` to the
  SDK; `BasePlugin.egress` and `HookContext.egress` reference the
  *same* per-plugin instance bound at load time. Per-plugin lifetime
  (not per-exchange) is what lets a batched/retry background flusher
  call `fetch` outside any hook. Discharges the plugins.md §8
  promise that has been carrying since Phase 1a.
- **ADR-0016** (`docs/decisions/0016-user-opt-in-env-knob.md`) —
  `LLMTRACK_USER_OPTED_IN` (default False), held as a `PluginHost`
  startup-time field, threaded into every `HookContext`. Smallest
  surface that lifts Mode R's content ceiling to L3 without bundling
  the per-task consent UX (which stays deferred per ADR-0006 §"Open
  questions").

Sequencing reality: this brings forward parts of Phase 2
(supabase_sink + a stub of the consent flow) and pays back the
Phase-1b egress-API debt. Phase 1c (`scope_guard`) is **explicitly
deferred** at the user's direction.

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

### Phase 1b loose ends (still deferred)

- `end_exchange` cleanup in the forwarder. Sidestepped for
  supabase_sink (per-plugin egress client lifetime is independent of
  per-exchange ctx), but the `_exchange_contexts` leak is real.
- Per-level shape refinement of `ctx.request_text()` (L1 hash,
  L2 scrubbed) — Phase 1c alongside scrubbers.
- Manifest `min_content_level` field — Phase 1c when scope_guard
  needs it.
- Response-side ctx accessors — Phase-2 Extractor.

## Next single step

**CP6: `client.py` + plugin `__init__` (queue + flusher + retry) +
unit tests.** Two artefacts:

- `client.py` — `SupabaseSinkClient.submit(record)`. Takes
  `(url, headers_factory)` so vendor coupling lives only here:
  swapping PostgREST → Edge Function later means rewriting *this
  file* (URL + auth + idempotency mapping + response parsing), not
  the plugin core. Builds JSON body (single-row PostgREST array),
  sets `apikey` + `Authorization: Bearer …` + `Prefer:
  resolution=ignore-duplicates` + `Content-Type: application/json`,
  delegates to `self.egress.fetch`. 201 = ok, 409 = idempotent skip,
  other = retry signal. The `service_role` key is read from env at
  call time via the `headers_factory` callable — never stored as a
  string attribute.
- `__init__.py` (overwrite the CP5 placeholder) —
  `SupabaseSinkPlugin`. `on_init` validates env (`LLMTRACK_PLUGIN_
  SUPABASE_SINK_URL`, `LLMTRACK_PLUGIN_SUPABASE_SINK_KEY`) and
  bails with a warning if missing. Per-exchange:
  `on_response_chunk` feeds the `ResponseAssembler`;
  `on_response_complete` builds an `ExchangeRecord` from the
  cached request body + assembled response + usage and enqueues it.
  Background flusher task: batch every N=8 records or T=2 s,
  retry with exponential backoff (3 attempts then drop +
  audit-warn), uses `self.egress.fetch`. `on_shutdown` drains the
  queue (CP7 will extend the timeout).

Tests via `PluginHarness` + a stub `ctx.egress` that records the
fetch calls — verify the chunk → complete → batch → fetch flow,
the 409 idempotent path, retry-then-drop, and shutdown drain.

Then in order: CP7 (`on_shutdown` timeout), CP8 (integration test +
signing), CP9 (manual e2e). Plan in the active worklog above.

## Blocking / decisions needed

- None. Phase 2 consent UX, manifest HTTPS-only validator, and
  Phase 1c (`scope_guard`) all explicitly deferred — see worklog
  Suggestions.

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
- [ ] **Phase 2 partial — `supabase_sink` reference plugin (in progress, 9 checkpoints)**
- [ ] Phase 1c — `scope_guard` plugin (deferred per user)
- [ ] Phase 2 remainder — `llm_tracker_server` routes, full per-task consent UX, contributor plugins

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
