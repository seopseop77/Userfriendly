# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b cleanup pass complete — paused at stop gates)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (cleanup pass complete; awaiting user input on stop gates)
- **Active task**: Cleanup-pass checkpoints A–G all landed. Paused for user input on Gate 1 (Transform handling policy) and Gate 2 (content-level → hook payload routing).

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
96305e1   core: layering polish + manifest allowed_modes tightening
6a08c9c   docs: Phase 1b checkpoint 12 — ADR-0008 housekeeping
6a76ea5   docs: Phase 1b checkpoint 11 — audit_log append-only triggers
2891e8f   storage: audit_log append-only DB triggers (ADR-0006)
b06623a   docs: Phase 1b checkpoint 10 — synthetic SSE block response
```

## Where we paused

Phase 1b cleanup-pass checkpoint G complete (commit 96305e1).
The seven auto-decidable cleanup-pass checkpoints (A–G) are all
closed:

- A: EgressGuard wired into proxy lifespan (e2ee4f0)
- B: signature verifier + signing CLI (3010aae)
- C: on_persisted ordering fix (a2bc3d4)
- D: synthetic SSE block response (b1724fa)
- E: audit_log append-only DB triggers (2891e8f)
- F: ADR-0008 housekeeping (6a08c9c)
- G: session_factory property + ADR-0009 (96305e1)

114/114 tests pass; touched files lint clean across all
checkpoints.

The remaining cleanup-pass items are **stop gates** that need
user input before Claude Code can land code:

- **Gate 1 — Transform handling policy.** `forwarder.py`
  currently ignores `Transform` returns from `before_forward`.
  Three sub-decisions: header policy (merge / overwrite /
  replace-all-headers), body policy (replace whole / not allowed
  / patch), multi-plugin chaining (chain in order / first-wins).
  Resolution needs an ADR before code (next slot is ADR-0010
  since 0009 was taken by Checkpoint G).
- **Gate 2 — content-level → hook payload routing.** Hooks today
  receive only `exchange_id`; Phase 1c's `scope_guard` needs
  user-message text. Three options on the table: (a) extend hook
  signatures with payloads, (b) `HookContext.request_text(level=...)`,
  (c) plugins query the DB. Once user picks, write ADR (next
  number after Gate 1's) and implement.

## Next single step

**STOP — Korean ping to user.** Surface both gates' decision
matrices and wait for the user's call. Resume with whichever
gate the user answers first; that gate becomes its own
ADR + checkpoint.

## Blocking / decisions needed

- **Gate 1**: Transform handling — header / body / multi-plugin
  policies.
- **Gate 2**: hook payload routing — option (a) / (b) / (c).

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
