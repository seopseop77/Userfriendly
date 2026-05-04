# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-05
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (in progress)
- **Active task**: Checkpoint 1 done; EgressGuard allowlist enforcement next.

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
04aa85f   security: hook timeout/exception isolation + manifest validation at load
b906f8d   docs: Phase 1a CLOSED — SDK complete, Phase 1b next
2652863   docs: expand plugins.md from skeleton to Phase 1a SDK reference
1ac807d   sdk: add PluginHarness test harness + tests
4e98e0c   sdk: add plugin.toml Pydantic schema + validator + tests
```

## Where we paused

Phase 1b checkpoint 1 complete (2026-05-05, commit 04aa85f). PluginHost now:
- Wraps every plugin hook in `asyncio.wait_for(5s)` — crash or timeout
  audits `plugin_fault` and returns the safe default; core never crashes.
- Validates `plugin.toml` at load time via `PluginManifest`; invalid or
  missing manifest → `manifest_rejected` audit entry, plugin skipped.
- `hello_world` plugin fixed: now imports `BasePlugin` from `llm_tracker_sdk`
  and ships a valid `plugin.toml`.
22/22 tests pass; ruff clean.

## Next single step

EgressGuard plugin-level allowlist enforcement (`packages/llm_tracker/src/llm_tracker/egress_guard/guard.py`):
- Accept a per-plugin `PluginManifest` in `check()`; enforce `egress_destinations` exact-match allowlist.
- Enforce mode policy: Mode L denies all plugin egress; Mode A/R allow per manifest.
- Write tests; each passing test = its own checkpoint per §5.3.

## Blocking / decisions needed

- None. Phase 1b is unblocked.
- ADR-0005 (plugin signing trust model) is still open; may surface during
  Phase 1b. Write ADR before implementing signing.

## Progress

- [x] Design v0.1 written
- [x] Framework pivot v0.2
- [x] English-only documentation pass
- [x] ADRs 0001–0007 sealed
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
