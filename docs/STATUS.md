# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b complete — checkpoint 18)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (**feature-complete**; deferred items listed below)
- **Active task**: Cleanup pass A–G + both stop gates closed. Phase 1c (`scope_guard`) is the next phase; opens with its own worklog.

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
75ff46a   core: HookContext for hook payload routing (ADR-0012)
4606ed0   docs: ADR-0012 — HookContext for hook payload routing (Gate 2)
bbb33e7   proxy: honour Transform from before_forward (ADR-0011)
cfbbb8e   docs: ADR-0011 — Transform handling policy (Gate 1)
654fbfb   docs: ADR-0010 — retroactive ratification of Block/Abort plugin field
```

## Where we paused

**Phase 1b is feature-complete.** Checkpoint 18 (commit
75ff46a) landed `HookContext` end-to-end: ADR-0012 is the
policy doc (commit 4606ed0); the SDK now ships `HookContext`
plus the moved `ContentLevel` primitive; every per-exchange
hook on `BasePlugin` carries `ctx: HookContext`; `PluginHost`
builds and threads the context per request via
`begin_exchange` / `_ctx_for`; the forwarder reads the request
body up-front and calls `begin_exchange` so plugins can read
the body lazily through `ctx.request_text(level=...)`; 14 new
tests pin propagation + per-mode degradation.

132/132 tests pass; touched files lint clean.

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

**Phase 1b is closed.** Next session opens Phase 1c —
`scope_guard` plugin. Open
`docs/worklog/<YYYY-MM-DD>-phase1c-scope-guard.md` and update
this STATUS.md to point at it; or land any of the loose ends
above first.

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
