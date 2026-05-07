# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-08 (CP9 — supabase_sink **shipped**; happy + Mode-L + allowlist-mismatch all verified against real traffic)
**Updated by**: Claude Code

## Current phase

- **Phase**: **Phase-2 partial — `supabase_sink` reference plugin shipped.** ADR-0007's named Phase-2 plugin is operational end-to-end against the operator's real Supabase project. Phase 1c (`scope_guard`) and the rest of Phase 2 (`llm_tracker_server` routes, full per-task consent UX, contributor plugins) remain on the deck.
- **Active task**: None. The workstream closed at CP9; pick the next direction (Phase 1c, Phase-1b loose ends, or a Phase-2 follow-on) when starting the next session.

## Active worklog

`docs/worklog/2026-05-07-supabase-sink.md` (closed; final entry under "Checkpoint 9")

## Recent commits

```
<CP9>     supabase-sink: CP9 e2e shipped (worklog/STATUS only)
f2f53b7   proxy: load .env at lifespan + refreshed .env.example
f420000   supabase-sink: e2e integration test + signed manifest
4294d10   plugin-host: SHUTDOWN_HOOK_TIMEOUT for sink drain
6ab979c   supabase-sink: client + plugin lifecycle + flusher
```

## Where we paused

**`supabase_sink` workstream closed.** ADR-0007's reference Mode-R
plugin is operational against the operator's real Supabase project
(7 rows in `public.exchanges` from Path 1). All three safety
paths verified against real traffic in CP9:

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

The deferred `Phase 1b loose ends` and the user-deferred
`Phase 1c` (`scope_guard`) remain the natural next directions.

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

**Pick a direction.** The supabase_sink workstream closed cleanly,
so the next session is free to choose. Three obvious candidates,
in roughly increasing scope:

1. **Phase-1b loose ends (small).** `end_exchange` cleanup in the
   forwarder is a bounded `_exchange_contexts` leak; per-level
   shape refinement of `ctx.request_text()` (L1 hash, L2 scrubbed)
   has been deferred since Phase 1a. Either is a small standalone
   checkpoint. Per-level shape work pairs naturally with whatever
   real consent / scrubber work comes next.
2. **Phase 2 follow-ons (medium).** A real per-task consent UX
   (replacing `LLMTRACK_USER_OPTED_IN` per ADR-0016 §"Open
   questions") needs its own design pass. `llm_tracker_server`
   routes / repositories / migrations are still empty (ADR-0007
   §2 demoted them to optional analysis app, not write path).
   `drift_metrics` contributor plugin is the planned third-party
   integration test target.
3. **Phase 1c — `scope_guard` (large).** User-deferred at the
   start of the supabase_sink workstream. Now that the egress
   API and signed-plugin pattern are ready, `scope_guard`'s
   Stage-2 LLM judge has the infra it needs. Will need its own
   planning pass — multiple ADR-worthy decisions (TaskDefinition
   schema, embedding judge sizing, eval-set acceptance criteria).
   Should re-open the planning interview.

Recommend starting from option 1 unless the user has a reason to
push 1c — Phase-1b loose ends are quick wins that unblock 1c
later.

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
- [x] **Phase 2 partial — `supabase_sink` reference plugin (CLOSED 2026-05-08, 9 commits 8712183 → CP9 finalize)**
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
