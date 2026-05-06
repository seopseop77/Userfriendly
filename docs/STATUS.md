# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b checkpoint 4 complete)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (in progress)
- **Active task**: Checkpoint 4 done; mode×capability policy enforcement next.

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
8ca5973   security: content-level ladder + per-mode ceiling
249f8bd   docs: Phase 1b checkpoint 3 — host↔guard wiring landed
f1a31cf   security: wire PluginHost manifests to EgressGuard
aa223f2   docs: Phase 1b checkpoint 2 — EgressGuard allowlist landed
5bafac1   security: EgressGuard allowlist + mode policy
```

## Where we paused

Phase 1b checkpoint 4 complete (2026-05-06, commit 8ca5973).
Content-level routing has its primitive landed:

- New module `llm_tracker.content_levels` exposes `ContentLevel`
  (IntEnum L0<L1<L2<L3), per-mode default + opt-in ceiling tables
  from design.md §7.1 / §8, `effective_ceiling(mode, *, user_opted_in)`,
  and `degrade(level, ceiling)` (`min`, never elevates).
- 14 new tests cover ladder ordering, per-mode default ceiling, the
  Mode-R-only opt-in elevation, unknown-mode rejection, and the
  never-elevate degrade contract.
- Pure primitive — no manifest changes, no hook-dispatch wiring.
  Two follow-up sub-pieces are blocked on architecture: a
  `min_content_level` manifest field (CLAUDE.md §10 → needs ADR)
  and a typed request/response payload object the dispatcher can
  degrade. Both flagged in worklog Handoff.

48/48 tests pass; new module + tests lint clean. Note: STATUS.md's
prior pointer to "design.md §7.5" was a typo — the section is
actually §7.1; corrected here.

## Next single step

Mode-by-mode capability policy enforcement at hook dispatch — the
remaining roadmap-1b line that is fully unblocked (no ADR needed,
policy already in design.md §6.3.3 / §8). Concrete shape:

1. Add a `(mode, capability) -> allowed` lookup (likely
   `llm_tracker.plugin_host.policy`) sourced from design.md §8.
2. At plugin load time (right after manifest validation), reject any
   plugin whose declared capabilities are denied under the active
   mode — write `capability_denied` and skip.
3. Tests: per-(mode, capability) parametrized matrix + a load-time
   test that a denied-capability manifest is rejected and a
   permitted manifest loads.

Defer manifest signature verification (independent, on Phase 1b
checklist; unblocked by ADR-0008) and proxy-boot wiring (Phase 1c)
until after this.

## Blocking / decisions needed

- None. Phase 1b is fully unblocked: ADR-0008 sealed the signing trust
  model, so manifest signature verification can be implemented when its
  turn comes in the Phase 1b checklist.

## Progress

- [x] Design v0.1 written
- [x] Framework pivot v0.2
- [x] English-only documentation pass
- [x] ADRs 0001–0008 sealed (0004 superseded by 0007)
- [x] Phase 0 — core skeleton (CLOSED 2026-05-04)
- [x] Phase 1a — plugin SDK (CLOSED 2026-05-05)
- [ ] Phase 1b — security boundary hardening (in progress)
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
