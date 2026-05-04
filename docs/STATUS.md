# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-05
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (Phase 1a CLOSED)
- **Active task**: None — Phase 1a complete; Phase 1b ready to start.

## Active worklog

Phase 1a worklog closed at `docs/worklog/2026-05-04-phase1a-sdk.md`.
Phase 1b should open: `docs/worklog/<YYYY-MM-DD>-phase1b-security.md`.

## Recent commits

```
2652863   docs: expand plugins.md from skeleton to Phase 1a SDK reference
1ac807d   sdk: add PluginHarness test harness + tests
4e98e0c   sdk: add plugin.toml Pydantic schema + validator + tests
60b379a   sdk: add capability token vocabulary (design.md §6.3.3)
c3b417e   sdk: move hook types and BasePlugin into llm_tracker_sdk
```

## Where we paused

Phase 1a fully closed (2026-05-05). `llm_tracker_sdk` now contains:
`Pass/Block/Transform/Abort`, `BasePlugin`, `capabilities` module,
`PluginManifest` schema + validator, `PluginHarness` test harness.
`docs/plugins.md` is a full SDK reference. 19/19 tests pass; ruff clean.

`@hook` decorator deferred (plain method override is sufficient; no runtime
benefit yet). Egress SDK API deferred to Phase 1b.

## Next single step

Begin Phase 1b — security boundary hardening. Per `docs/roadmap.md`:

1. Open worklog `docs/worklog/<YYYY-MM-DD>-phase1b-security.md`.
2. Read `docs/design.md §7` (security model) and `docs/decisions/ADR-0006`
   for the full threat model.
3. Hook dispatch timeout + exception isolation in `PluginHost` — a plugin
   fault must not crash the core.
4. Manifest loading: validate `plugin.toml` via `PluginManifest` at plugin
   load time; reject plugins with invalid manifests.
5. Each step = its own checkpoint.

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
- [ ] Phase 1b — security boundary hardening
- [ ] Phase 1c — `scope_guard` plugin
- [ ] Phase 2+ — Mode R sink, third-party plugins

## Blocking / decisions needed

- None. ADR-0003 was the last blocker; it is now Accepted.
- Two decisions deferred to mid-Phase-1: plugin signing trust model
  (ADR-0005 open), Stage 2 LLM judge model (ADR-0002 open). Neither blocks
  Phase 1a.

## Progress

- [x] Design v0.1 written
- [x] Framework pivot v0.2
- [x] English-only documentation pass
- [x] ADRs 0001–0007 sealed (0004 superseded by 0007; 0003 revised &
      Accepted on 2026-05-03)
- [x] Phase 0 — core skeleton (CLOSED 2026-05-04)
- [ ] Phase 1a — plugin SDK
- [ ] Phase 1b — security boundary hardening
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
