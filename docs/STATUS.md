# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-09 (CP2 of Phase-1b loose-ends — `HookContext` per-level shape landed; closing checkpoint next)
**Updated by**: Claude Code

## Current phase

- **Phase**: **Phase-1b loose-ends nearly closed.** CP1 (`end_exchange` leak fix) and CP2 (`HookContext` per-level shape: L1 → None for `request_text`; new `request_hash` / `request_length` accessors) both landed. The closing checkpoint is a docs-only commit that retires "Phase 1b loose ends" from this STATUS and migrates the genuinely-Phase-1c-blocked items under "Phase 1c prerequisites".
- **Active task**: Closing checkpoint of `2026-05-09-phase1b-loose-ends`.

## Active worklog

`docs/worklog/2026-05-09-phase1b-loose-ends.md` (CP1 + CP2 closed; closing checkpoint pending)

## Recent commits

```
86caf03   sdk: per-level shape for HookContext request accessors  (Phase-1b CP2)
14b6f7a   docs: open Phase-1b loose-ends worklog; CP1 closed
86acecd   proxy: pair begin_exchange with end_exchange             (Phase-1b CP1)
2a21f4d   supabase-sink: CP9 manual e2e shipped
f2f53b7   proxy: load .env at lifespan + refreshed .env.example
```

## Where we paused

**Phase-1b loose-ends CP1 + CP2 closed.** Two surgical refinements
landed:

- **CP1 (commit 86acecd)** — the forwarder now pairs
  `PluginHost.begin_exchange` with `end_exchange` on every return
  path (normal completion, Block-from-`on_request_received`,
  Block-from-`before_forward`, Abort-from-`on_upstream_response_start`).
  The cleanup runs from the generators that `StreamingResponse`
  iterates because `forward_request` returns to Starlette before
  the generator code runs. `_exchange_contexts == {}` after each
  path is pinned by
  `tests/proxy/test_exchange_context_lifecycle.py` (3 tests).
- **CP2 (commit 86caf03)** — `HookContext.request_text(level)` now
  returns `None` for any effective level ≤ L1 per design.md §7.1.
  Two new accessors fill the L1 escape hatch: `request_hash()`
  (hex SHA-256 of `_raw_request_body`) and `request_length()`
  (byte length), both gated on `effective_ceiling() >= L1`. L2
  still returns raw text today; the scrubbed shape lands with
  Phase 1c scrubbers and is pinned by a regression test so the
  switch is visible. `docs/plugins.md` §3.1 documents the
  per-level table; the test-only `keyword_block` fixture moved to
  Mode R + opt-in (the plugin needs raw text to function).

**Next: closing checkpoint** — docs-only commit that retires
"Phase 1b loose ends" from this STATUS and migrates the three
remaining items (L2 scrubbed shape, manifest `min_content_level`,
response-side `ctx` accessors) under a new "Phase 1c prerequisites"
heading. They're no longer Phase-1b debt.

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

**Closing checkpoint of `2026-05-09-phase1b-loose-ends`** — a
docs-only commit (scope `docs:`) that:

1. Drops the "Phase 1b loose ends (still deferred)" subheading
   from this STATUS.
2. Adds a new top-level heading "Phase 1c prerequisites" that
   collects the three items legitimately blocked on Phase 1c:
   - L2 scrubbed shape of `request_text` (needs scrubber primitives;
     pinned by `test_request_text_returns_body_at_l2_when_ceiling_allows`
     so the shape change is test-visible).
   - Manifest `min_content_level` field (needs scope_guard).
   - Response-side `ctx` accessors (`response_text`,
     `tool_call_inputs`) — needs Phase 2 Extractor.
3. Updates the active worklog "Handoff" to declare Phase 1b
   loose-ends workstream closed.
4. Refreshes "Next single step" to re-state the choice between
   Phase 1c kickoff (with planning interview for TaskDefinition,
   judge sizing, eval-set acceptance criteria) and Phase 2
   follow-ons (per-task consent UX, `llm_tracker_server` routes,
   `drift_metrics` contributor plugin).
5. Bumps "Last updated" to today.

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
