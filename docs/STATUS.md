# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-08 (CP7 — `SHUTDOWN_HOOK_TIMEOUT` split for sink-drain headroom)
**Updated by**: Claude Code

## Current phase

- **Phase**: **Phase-2 partial — supabase_sink reference plugin (early)**. Phase 1c (`scope_guard`) explicitly deferred per user. The egress client SDK is a Phase-1b debt repayment forced by this work; the consent env knob is the smallest surface that lifts Mode R's ceiling without bundling the full Phase-2 consent UX (ADR-0016).
- **Active task**: 9-checkpoint plan for `llm_tracker_plugin_supabase_sink`. CP1–CP7 done. CP8 (integration test + manifest signing) is next.

## Active worklog

`docs/worklog/2026-05-07-supabase-sink.md`

## Recent commits

```
<CP7>     plugin-host: SHUTDOWN_HOOK_TIMEOUT for sink drain
6ab979c   supabase-sink: client + plugin lifecycle + flusher
9088825   supabase-sink: package skeleton + parser + tests
a3b5dff   supabase-sink: schema migrated + RLS enabled
dff7e3e   config: LLMTRACK_USER_OPTED_IN env + PluginHost field
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

**CP8: integration test + manifest signing.** Two artefacts:

- `tests/integration/test_supabase_sink_e2e.py` (new) — boot a
  `PluginHost` in Mode R + `user_opted_in=True` with a stubbed
  `httpx.AsyncClient` (mocks Supabase) and the supabase_sink
  manifest registered. Drive an exchange end-to-end through the
  per-exchange dispatchers (chunk → complete → flusher → mocked
  PostgREST) and assert: (a) a single POST hit the configured URL
  with the expected JSON-array body and PostgREST headers; (b) the
  `egress_attempt outcome=ok` row is in `audit_log`. Negative path:
  pull the destination URL out of the manifest's
  `egress_destinations` (so `EgressGuard.check` denies) and confirm
  no POST fires + an `egress_blocked` row appears with the right
  `reason`. Mode L safety: the same plugin loaded in Mode L is
  rejected at `load_plugins` time (no entry in
  `loaded_plugins()`).
- Sign the manifest via the project's `minseop` key:
  `python -m llm_tracker.cli.signing sign packages/llm_tracker_plugin_supabase_sink/src/llm_tracker_plugin_supabase_sink/plugin.toml`
  (or whatever the existing signing CLI invocation is — mirror
  what `token_counter` / `keyword_block` did in
  `docs/worklog/2026-05-06-test-plugins.md`). Resulting
  `plugin.toml.sig` is checked in.

Then CP9: manual e2e against the real Supabase project (apply env
vars, run a small `claude-manage` request, verify the row arrives
via `mcp__supabase__execute_sql`, verify the audit log).

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
