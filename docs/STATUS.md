# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase-1b verification — test plugins green)
**Updated by**: Claude Code

## Current phase

- **Phase**: Pre-Phase-1c verification side-quest (TEST-ONLY plugins). Phase 1b sealed at commit 75ff46a; Phase 1c (`scope_guard`) still on deck.
- **Active task**: Two TEST-ONLY plugins (`token_counter`, `keyword_block`) landed and verified end-to-end against the existing hook chain.

## Active worklog

`docs/worklog/2026-05-06-test-plugins.md`

## Recent commits

```
2c28f68   plugins: TEST-ONLY token_counter + keyword_block
102e69b   docs: Phase 1b checkpoints 17+18 — Gate 2 closed; phase complete
75ff46a   core: HookContext for hook payload routing (ADR-0012)
4606ed0   docs: ADR-0012 — HookContext for hook payload routing (Gate 2)
bbb33e7   proxy: honour Transform from before_forward (ADR-0011)
```

## Where we paused

**Verification side-quest landed before Phase 1c.** Two TEST-ONLY
plugins under `packages/` exercise the hook chain end-to-end:

- `token_counter` (commit 2c28f68): `on_response_chunk` →
  `on_response_complete`. Buffers Anthropic SSE and writes
  per-exchange usage rows to a sidecar SQLite at
  `var/plugin_token_counter.db`.
- `keyword_block` (commit 2c28f68): `on_request_received`. Returns
  `Block(...)` when the request body matches a forbidden keyword
  (env-configurable via `LLMTRACK_KEYWORDS_BLOCK_LIST`).

Both manifests are signed by the bundled `minseop` trust key and
loaded successfully by `PluginHost.load_plugins()` alongside
`hello_world` (smoke-tested). 150/150 tests pass; ruff clean.

**Phase 1b remains feature-complete** (commit 75ff46a closed it).

Closed-checkpoint roll-up (cleanup pass A–G + both stop gates):

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

### Phase 1b loose ends

Known-deferred; each would be its own checkpoint when picked up:

- `end_exchange` cleanup in the forwarder (Block/Abort early
  returns + `generate()` finally). Bounded leak only.
- Per-level shape refinement of `ctx.request_text()` (L1 hash,
  L2 scrubbed) — wired in Phase 1c alongside scrubbers.
- Manifest `min_content_level` field — Phase 1c when scope_guard
  needs it.
- Response-side ctx accessors — wait for Extractor / structured
  response data.

## Next single step

Two paths, pick one:

1. **Manual real-traffic e2e** with both test plugins loaded — start
   `llm-tracker start --mode L`, point `ANTHROPIC_BASE_URL` at it,
   send one real Claude Code request, and inspect both
   `var/llm_tracker.db` (core) and `var/plugin_token_counter.db`
   (sidecar). This is the highest-confidence verification of
   everything Phase 1a/1b shipped.
2. **Open Phase 1c — `scope_guard` plugin.** Create
   `docs/worklog/<YYYY-MM-DD>-phase1c-scope-guard.md`, point this
   STATUS.md at it, and schedule removal of the now-redundant
   `keyword_block` test plugin in that worklog.

Both `keyword_block` (Phase 1c overlap) and `token_counter` (Phase 2
Extractor overlap) are explicit throwaways — track their removal
when the proper replacement lands.

## Blocking / decisions needed

- None.

## Progress

- [x] Design v0.1 written
- [x] Framework pivot v0.2
- [x] English-only documentation pass
- [x] ADRs 0001–0008 sealed (0004 superseded by 0007)
- [x] Phase 0 — core skeleton (CLOSED 2026-05-04)
- [x] Phase 1a — plugin SDK (CLOSED 2026-05-05)
- [x] Phase 1b — security boundary hardening (CLOSED 2026-05-06)
- [x] Pre-Phase-1c verification — TEST-ONLY plugins (token_counter, keyword_block) (2026-05-06, commit 2c28f68)
- [ ] Phase 1c — `scope_guard` plugin
- [ ] Phase 2+ — Mode R sink, third-party plugins

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
