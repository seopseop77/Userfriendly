# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-09 (Phase-1b loose-ends workstream **closed**; pick Phase 1c or a Phase-2 follow-on next)
**Updated by**: Claude Code

## Current phase

- **Phase**: **Phase-1b loose-ends closed.** Two surgical refinements landed today (CP1 = `end_exchange` leak fix in the forwarder; CP2 = `HookContext` per-level shape with new `request_hash` / `request_length` accessors). The remaining items previously listed as "Phase 1b loose ends" were genuinely Phase-1c-blocked; they now live under "Phase 1c prerequisites" below.
- **Active task**: None. Pick the next direction (Phase 1c kickoff or a Phase-2 follow-on) when starting the next session.

## Active worklog

`docs/worklog/2026-05-09-phase1b-loose-ends.md` (closed; final entry under "Handoff")

## Recent commits

```
8d4422b   docs: Phase-1b loose-ends CP2 closed
86caf03   sdk: per-level shape for HookContext request accessors  (Phase-1b CP2)
14b6f7a   docs: open Phase-1b loose-ends worklog; CP1 closed
86acecd   proxy: pair begin_exchange with end_exchange             (Phase-1b CP1)
2a21f4d   supabase-sink: CP9 manual e2e shipped
```

(The closing docs commit that produced this STATUS revision will appear at the top of `git log -5` in the next session.)

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

The closing checkpoint (this commit) retired the "Phase 1b loose
ends" subsection from STATUS and migrated the three genuinely-Phase-
1c-blocked items (L2 scrubbed shape, manifest `min_content_level`,
response-side `ctx` accessors) under "Phase 1c prerequisites" below
— they were never Phase-1b debt.

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

## Phase 1c prerequisites

These three items are blocked on Phase 1c (scrubber primitives,
`scope_guard`, the Phase-2 Extractor) — not Phase-1b debt. They're
documented here so the next session knows what `scope_guard` and the
Extractor unlock when they land.

- **L2 scrubbed shape of `request_text`**. Today
  `HookContext.request_text(L2)` returns the raw decoded body — same
  bytes as L3. Per design.md §7.1 L2 should be the scrubbed body
  (secrets / PII / paths / emails / IPs removed). The switch needs
  the Phase-1c scrubber primitives. Pinned by
  `test_hook_context.py::test_request_text_returns_body_at_l2_when_ceiling_allows`
  so the eventual change is test-visible.
- **Manifest `min_content_level` field** (ADR-0012 §"Open
  questions"). Plugins should declare the lowest content level they
  can function at; the host can then short-circuit dispatch when the
  effective ceiling is below it. Add this when `scope_guard` becomes
  the first plugin that actually needs it; separate ADR (refines
  ADR-0012).
- **Response-side `ctx` accessors** (`response_text`,
  `tool_call_inputs`, etc.). ADR-0012 ships only the request-side
  accessors. Response-side data needs the Phase-2 Extractor to
  surface structured response records first; separate ADR if the
  semantics surface anything non-obvious (e.g. partial vs assembled).

## Next single step

**Pick a direction.** Phase-1b loose-ends and the supabase_sink
workstream are both closed cleanly, so the next session is free to
choose. Two obvious candidates:

1. **Phase 1c — `scope_guard` (large; user-deferred so far).** Now
   that the egress API, signed-plugin pattern, and the L1 escape
   hatch (`request_hash` / `request_length`) are all ready, the
   Stage-2 LLM judge has the infra it needs. Re-open the planning
   interview — multiple ADR-worthy decisions: TaskDefinition
   schema, embedding judge sizing, eval-set acceptance criteria,
   manifest `min_content_level` field. The "Phase 1c prerequisites"
   section above is what 1c unlocks.
2. **Phase 2 follow-ons (medium).** A real per-task consent UX
   (replacing `LLMTRACK_USER_OPTED_IN` per ADR-0016 §"Open
   questions") needs its own design pass. `llm_tracker_server`
   routes / repositories / migrations are still empty (ADR-0007
   §2 demoted them to optional analysis app, not write path).
   `drift_metrics` contributor plugin is the planned third-party
   integration test target.

Recommend Phase 1c next — the security model and SDK contract are
now stable enough that scope_guard can be designed against a fixed
target, and the planning interview will surface everything else.

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
- [x] **Phase 1b loose-ends (CLOSED 2026-05-09, commits 86acecd / 14b6f7a / 86caf03 / 8d4422b + closing docs commit)**
- [ ] Phase 1c — `scope_guard` plugin (recommended next)
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
