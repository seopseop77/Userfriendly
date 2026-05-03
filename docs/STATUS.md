# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-03 (Claude Code; Phase 0 checkpoint 3 — SQLite schema done)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 0 — core framework skeleton (in progress)
- **Active task**: Typer CLI skeletons (init, start, audit) + PluginHost scaffold

## Active worklog

`docs/worklog/2026-05-03-phase0-skeleton.md`

## Recent commits

```
6ce1267 storage: add SQLAlchemy models + Alembic initial migration
cc62568 docs: checkpoint 2 — proxy forwarder done, next is Alembic + SQLite schema
453e590 proxy: add FastAPI catch-all route + httpx SSE forwarder with tee
d4fb688 docs: record commit hash b43d82d in worklog and STATUS
b43d82d deps: fill in pyproject.toml runtime dependencies for Phase 0
```

## Where we paused

Phase 0 checkpoint 3 complete: SQLAlchemy ORM models + Alembic migration created
for all 4 core tables (exchanges, events, tool_calls, audit_log). `alembic upgrade
head` verified. Next: Typer CLI skeletons + PluginHost scaffold.

## Next single step

Phase 0 checkpoint 3 done. Next: Typer CLI skeletons + PluginHost scaffold.

Concretely:
1. Create `src/llm_tracker/cli/` with Typer app and three stub commands:
   `init` (create config + run `alembic upgrade head`), `start` (boot uvicorn),
   `audit` (query audit_log).
2. Wire `llm-tracker = "llm_tracker.cli:app"` in `pyproject.toml [project.scripts]`.
3. Create `src/llm_tracker/plugin_host/` skeleton: `PluginHost` class, entry-point
   loader, hook dispatcher stub (8 hooks invoked in order, no plugin logic yet).
4. Invoke all 8 hooks at the correct points in `forwarder.py` (empty dispatch only).
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
