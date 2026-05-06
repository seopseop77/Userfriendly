# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b checkpoint 10 complete)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (cleanup pass in progress)
- **Active task**: Synthetic SSE block response landed; audit_log append-only triggers next (Checkpoint E).

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
b1724fa   proxy: synthetic SSE block response per ADR-0002 §3
ebb581a   docs: Phase 1b checkpoint 9 — on_persisted ordering fix
a2bc3d4   proxy: fix on_persisted ordering relative to DB write
5fd58f0   docs: Phase 1b checkpoint 8 — manifest signature verifier wired
3010aae   security: wire manifest signature verifier into loader
```

## Where we paused

Phase 1b cleanup-pass checkpoint D complete (2026-05-06, commit
b1724fa). The forwarder no longer returns HTTP 503 plain text on
Block / Abort. Instead it emits the documented six-event Anthropic
SSE 200 stream (`message_start → content_block_start →
content_block_delta` carrying `"[llm-tracker] <reason>"` →
`content_block_stop → message_delta` with
`stop_reason="end_turn"` → `message_stop`). `tool_use` is never
emitted. The block path also persists an `Exchange` row with
`blocked_by=<plugin>` via the new `record_exchange_blocked`
helper.

SDK side: `Block` and `Abort` gain an additive optional
`plugin: str = ""` field that the host sets to the blocking
plugin's name. Backward compatible — plugin code that builds
`Block(reason="…")` is unaffected.

109/109 tests pass; touched files lint clean. The new test parses
the synthetic SSE bytes back into events, asserts the order, the
`[llm-tracker]` text payload, the absence of `tool_use`, and the
persisted `blocked_by`.

Cleanup pass progress: A, B, C, D closed (proxy-boot wiring,
manifest signing, `on_persisted` ordering, synthetic SSE block).
Remaining: E (audit_log triggers), F (ADR-0008 housekeeping),
G (session_factory property + ADR-0009 for `allowed_modes`
default). Then Gates 1/2 with user input.

## Next single step

**Checkpoint E — `audit_log` append-only DB enforcement.** Add
an Alembic migration installing two SQLite triggers,
`audit_log_no_update` (BEFORE UPDATE) and `audit_log_no_delete`
(BEFORE DELETE), each `RAISE(ABORT, '...append-only...')`. Remove
the "deferred to Phase 1b" comment in `storage/models.py`. Test:
insert an audit row, then assert that UPDATE and DELETE both
raise.

## Blocking / decisions needed

- None for Checkpoint E.
- Gates 1 (Transform handling) and 2 (hook payload routing)
  remain deferred to their respective checkpoints.

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
