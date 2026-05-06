# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b checkpoint 9 complete)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (cleanup pass in progress)
- **Active task**: `on_persisted` ordering fixed; synthetic SSE block response is next (Checkpoint D).

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
a2bc3d4   proxy: fix on_persisted ordering relative to DB write
5fd58f0   docs: Phase 1b checkpoint 8 — manifest signature verifier wired
3010aae   security: wire manifest signature verifier into loader
592ccc4   docs: Phase 1b checkpoint 7 — EgressGuard wired into proxy lifespan
e2ee4f0   proxy: wire EgressGuard into lifespan
```

## Where we paused

Phase 1b cleanup-pass checkpoint C complete (2026-05-06, commit
a2bc3d4). Forwarder now writes the `exchanges` row before
dispatching `on_persisted` so plugins can read it back in the
hook (design.md §6.3.2). Regression test (`tests/proxy/test_forwarder.py`)
injects a `_ReaderPlugin` whose `on_persisted` opens a session and
asserts the row exists. Drives `forward_request` directly with a
constructed Starlette `Request` + respx-mocked upstream so it
doesn't depend on the FastAPI lifespan / Settings.

108/108 tests pass; touched files lint clean. Side effect:
`tests/proxy/test_forwarder.py`'s pre-existing I001 was
incidentally cleaned up by the auto-fix on the new imports.

Cleanup pass progress: A, B, C closed (proxy-boot wiring,
manifest signing, `on_persisted` ordering). Remaining: D
(synthetic SSE block response), E (audit_log triggers), F
(ADR-0008 housekeeping), G (session_factory property + ADR-0009
for `allowed_modes` default). Then Gates 1/2 with user input.

## Next single step

**Checkpoint D — synthetic SSE block response (ADR-0002 §3).**
`forwarder.py::_block_response` currently returns HTTP 503 plain
text — exactly the option ADR-0002 said NOT to use. Replace with
a synthetic Anthropic SSE 200 OK stream (sequence per design.md
§5.4):

`message_start → content_block_start → content_block_delta`
(single `text_delta` carrying the `[llm-tracker]` prefix + reason)
`→ content_block_stop → message_delta` (`stop_reason="end_turn"`)
`→ message_stop`

Status 200, `content-type: text/event-stream`. **Never** emit
`tool_use`. The block path must also persist an `Exchange` row
with `blocked_by=<plugin>` populated (column already on the
model; add a `record_exchange_blocked` helper next to
`record_exchange_timing`).

Tests: drive a Block stream through an httpx client, parse it
cleanly as an Anthropic SSE message, assert each event appears
in order, `tool_use` is absent, and the persisted `Exchange` row
carries `blocked_by`.

## Blocking / decisions needed

- None for Checkpoint D.
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
