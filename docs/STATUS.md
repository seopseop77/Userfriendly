# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b checkpoint 12 complete)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (cleanup pass in progress)
- **Active task**: ADR-0008 housekeeping landed; small polish + ADR-0009 next (Checkpoint G).

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
6a76ea5   docs: Phase 1b checkpoint 11 — audit_log append-only triggers
2891e8f   storage: audit_log append-only DB triggers (ADR-0006)
b06623a   docs: Phase 1b checkpoint 10 — synthetic SSE block response
b1724fa   proxy: synthetic SSE block response per ADR-0002 §3
ebb581a   docs: Phase 1b checkpoint 9 — on_persisted ordering fix
```

## Where we paused

Phase 1b cleanup-pass checkpoint F complete (docs only). ADR-0008
now distinguishes Phase-1b-resolved sub-decisions (canonicalization
= byte-exact, sibling `plugin.toml.sig`, signer+signature blob,
`[[key]]` registry, `generate-key`/`sign-plugin` CLI,
developer-signed reference plugin) from items that remain deferred
(boot-time verification cache, key rotation policy, revocation
mechanism).

Cleanup pass progress: A, B, C, D, E, F closed. Remaining: G
(`session_factory` read-only property on PluginHost + ADR-0009
for `allowed_modes` default tightening + manifest validator
update). Then Gates 1/2 with user input.

## Next single step

**Checkpoint G — small polish (one commit).**

1. `PluginHost.session_factory` exposed as a read-only property;
   `forwarder.py` reaches in via the property instead of the
   underscore name.
2. ADR-0009 "Plugin manifest `allowed_modes` becomes
   required-non-empty" (short, single-decision ADR).
3. `llm_tracker_sdk/manifest.py`: drop the `list(VALID_MODES)`
   default, mark required (`Field(...)`), add a validator
   rejecting an empty list. `hello_world`'s manifest already
   declares the full mode set, so neither it nor its `.sig` need
   to change.

## Blocking / decisions needed

- None for Checkpoint G.
- Gates 1 (Transform handling) and 2 (hook payload routing)
  require user input when reached.

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
