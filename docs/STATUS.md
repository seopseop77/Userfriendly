# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b checkpoint 2 complete)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (in progress)
- **Active task**: Checkpoint 2 done; PluginHost ↔ EgressGuard wiring next.

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
5bafac1   security: EgressGuard allowlist + mode policy
f8447b2   docs: STATUS + worklog reflect ADR-0008 sealed
d39c487   docs: ADR-0008 plugin signing trust model
38a1fb2   docs: open Phase 1b worklog; update STATUS to checkpoint 1
04aa85f   security: hook timeout/exception isolation + manifest validation at load
```

## Where we paused

Phase 1b checkpoint 2 complete (2026-05-06, commit 5bafac1). EgressGuard
now enforces the design.md §7.3 / §8 policy:

- `register(manifest)` attaches a `PluginManifest` per plugin name.
- `check()` walks a six-step decision: Mode L always denies; otherwise
  the plugin must be registered, the current mode must be in
  `allowed_modes`, the requested capability must be declared, the URL
  must exact-match `egress_destinations`, and Mode A requires exactly
  one declared destination.
- Every check writes `egress_attempt`/`egress_blocked` with mode and
  denial reason in `detail_json` — the "capability use audit-logged"
  Phase 1b checklist item is subsumed by this.

32/32 tests pass (10 new in `test_egress_guard.py`); the new files lint
clean. Five pre-existing ruff errors in unrelated files noted in
worklog Suggestions; not touched per CLAUDE.md §9.

## Next single step

Thread the validated `PluginManifest` from `PluginHost.load_plugins()`
into `EgressGuard.register()`. Today the host validates the manifest
and discards it, so the guard has nothing to enforce against in a real
boot. Concretely:

1. Give `PluginHost.__init__` an optional `egress_guard: EgressGuard | None`.
2. After `_find_manifest()` succeeds, call `egress_guard.register(manifest)`
   before instantiating the plugin.
3. Add an integration test: load a real fixture plugin, then call
   `egress_guard.check(...)` for its declared destination — expect
   `True` under Mode R, `False` under Mode L.

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
