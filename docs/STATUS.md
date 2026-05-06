# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b checkpoint 3 complete)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (in progress)
- **Active task**: Checkpoint 3 done; content-level routing (L0–L3) next.

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
f1a31cf   security: wire PluginHost manifests to EgressGuard
aa223f2   docs: Phase 1b checkpoint 2 — EgressGuard allowlist landed
5bafac1   security: EgressGuard allowlist + mode policy
f8447b2   docs: STATUS + worklog reflect ADR-0008 sealed
d39c487   docs: ADR-0008 plugin signing trust model
```

## Where we paused

Phase 1b checkpoint 3 complete (2026-05-06, commit f1a31cf). The
plugin loading lifecycle is end-to-end wired for egress enforcement:

- `PluginHost.__init__` takes an optional `egress_guard: EgressGuard | None`.
- `load_plugins()` calls `egress_guard.register(manifest)` after a
  successful `_find_manifest()` and before plugin instantiation. A
  rejected manifest never reaches `register()`, so the guard's denial
  short-circuit (`no_manifest_registered`) still bites for malformed
  plugins.
- Two new tests in `test_plugin_host.py` pin both paths: a registered
  manifest's declared destination passes `EgressGuard.check()` under
  Mode R; a manifest-rejection path leaves the guard denying.

34/34 tests pass; changed files lint clean. The five pre-existing
ruff errors in unrelated files (CLAUDE.md §9 — not in scope) remain
flagged in worklog Suggestions.

## Next single step

Implement content-level routing (L0–L3): the core must degrade data
to the operator-approved level for the current mode *before* it is
handed to plugins. Re-read `docs/design.md §7.5` first; tentative
shape (subject to that reading):

1. Define an `L0 < L1 < L2 < L3` ladder in a shared module
   (`llm_tracker.content_levels` or alongside `llm_tracker.scrubbers`).
2. Encode the per-mode max level from design.md §8.
3. Insert a degrade step in the request/response path before the
   hook dispatcher passes payloads to plugins.
4. Tests: per-level redaction expectations + per-mode max-level
   table-driven cases.

Defer proxy-boot wiring (constructing `EgressGuard` and passing it
into `PluginHost` from `cli/main.py`) until Phase 1c — the framework
plumbing is done; only the boot path is missing.

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
