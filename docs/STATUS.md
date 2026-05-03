# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-03 (Claude Code; Phase 0 checkpoint 4 — CLI + PluginHost done)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 0 — core framework skeleton (in progress)
- **Active task**: EgressGuard skeleton + hello_world plugin + end-to-end test

## Active worklog

`docs/worklog/2026-05-03-phase0-skeleton.md`

## Recent commits

```
0aaa698 feat: add CLI, PluginHost, AuditLog, config, and hook dispatch
864e854 docs: checkpoint 3 — SQLite schema done, next CLI + PluginHost
6ce1267 storage: add SQLAlchemy models + Alembic initial migration
cc62568 docs: checkpoint 2 — proxy forwarder done, next is Alembic + SQLite schema
453e590 proxy: add FastAPI catch-all route + httpx SSE forwarder with tee
```

## Where we paused

Phase 0 checkpoint 4 complete: CLI (init/start/audit), PluginHost (8 hooks dispatched,
audit logged), pydantic-settings config, EgressGuard and hello_world plugin remain.

## Next single step

Phase 0 checkpoint 4 done. Next: EgressGuard skeleton + hello_world plugin + end-to-end.

Concretely:
1. Create `src/llm_tracker/egress_guard/` — `EgressGuard` class that allows only the
   LLM upstream in Mode L; all attempts logged to audit_log.
2. Create `src/llm_tracker_plugin_hello_world/` — minimal no-op plugin that registers
   via entry point, loads via PluginHost, and shows hook calls in audit log.
3. Wire the hello_world entry point in `pyproject.toml` dev extras.
4. Verify end-to-end: `llm-tracker init` → `llm-tracker start` → proxy a test request →
   `llm-tracker audit` shows hook entries.
5. Checkpoint: commit + worklog + STATUS update.

## Blocking / decisions needed

- None for starting Phase 0.
- Before entering Phase 1, ADR-0003 (distribution) must be updated to
  reflect the framework + plugin split. Not blocking now.

## Progress

- [x] Design v0.1 written
- [x] Framework pivot v0.2
- [x] ADRs 0001–0007 sealed (0004 superseded by 0007)
- [x] English-only documentation pass
- [ ] Phase 0 — core skeleton
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
