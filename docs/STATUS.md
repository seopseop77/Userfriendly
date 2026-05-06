# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b checkpoint 14 — ADR-0010 retroactive)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (cleanup pass A–G + retroactive SDK ADR closed; gates decided, implementation pending)
- **Active task**: ADR-0010 (Block/Abort plugin field) ratified retroactively. Next is ADR-0011 (Gate 1 — Transform handling) followed by implementation, then Gate 2 (ADR-0012 — HookContext).

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
bda318c   docs: Phase 1b checkpoint 13 — cleanup pass complete; gates open
96305e1   core: layering polish + manifest allowed_modes tightening
6a08c9c   docs: Phase 1b checkpoint 12 — ADR-0008 housekeeping
6a76ea5   docs: Phase 1b checkpoint 11 — audit_log append-only triggers
2891e8f   storage: audit_log append-only DB triggers (ADR-0006)
```

## Where we paused

User has answered both stop gates and ratified the SDK
field-addition retroactively as ADR-0010.

- **ADR-0010 (retroactive, this checkpoint, docs only)**: Block /
  Abort `plugin: str = ""` field is the chosen contract for
  conveying the blocking plugin's name from the dispatcher to
  the forwarder.
- **Gate 1 → ADR-0011 next**: Transform handling policy. Header
  merge (plugin wins on conflict), body replace whole, multi-plugin
  first-wins.
- **Gate 2 → ADR-0012 after Gate 1 lands**: Hook payload routing
  via option (b) `HookContext`. Lazy accessors with mode × opt-in
  degradation at access time. `min_content_level` manifest field
  deferred to Phase 1c.

The auto-decidable cleanup-pass checkpoints (A–G) plus the
retroactive ADR-0010 are all closed (114/114 tests pass; touched
files lint clean):

- A: EgressGuard wired into proxy lifespan (e2ee4f0)
- B: signature verifier + signing CLI (3010aae)
- C: on_persisted ordering fix (a2bc3d4)
- D: synthetic SSE block response (b1724fa)
- E: audit_log append-only DB triggers (2891e8f)
- F: ADR-0008 housekeeping (6a08c9c)
- G: session_factory property + ADR-0009 (96305e1)
- 14: ADR-0010 retroactive (this commit)

## Next single step

**Write ADR-0011 — Transform handling policy.** Path
`docs/decisions/0011-transform-policy.md`. Document the user's
three decisions: header merge with plugin-wins on conflict, body
replace whole when `Transform.body is not None`, multi-plugin
first-wins. Commit with scope `docs`. After the ADR commits,
implement Transform handling in `forwarder.py` (header merge +
body replacement) and stop `PluginHost.before_forward` from
calling subsequent plugins after the first non-`Pass` result.
Each passing test group is its own checkpoint.

Strict order: ADR-0011 → Gate 1 implementation + tests
(committed and verified) → ADR-0012 → Gate 2 implementation +
tests. **Do not start Gate 2 until Gate 1 is fully committed
and tested.**

## Blocking / decisions needed

- None. All gates decided; implementation queue is unblocked.

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
