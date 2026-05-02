# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-03 (Cowork; English-only documentation pass
complete, karpathy guidelines integrated; Phase 0 not yet started)
**Updated by**: Claude Cowork

## Current phase

- **Phase**: Phase 0 — core framework skeleton (not started)
- **Active task**: none (waiting for first Phase 0 instruction)

## Active worklog

None. When Phase 0 work begins, Claude Code creates
`docs/worklog/<YYYY-MM-DD>-phase0-<slug>.md`.

## Recent commits

```
<latest> docs: translate to English, integrate karpathy guidelines, add language rule
5231e3f  docs: add session-resume infrastructure for cutoff resilience
2202434  docs: pivot to framework-first architecture with plugin model
9ad6e88  docs: lock central server stack and add git auto-commit convention
c0f67f9  feat: base structure
```

## Where we paused

Design documents, ADRs, the framework pivot, and the English-only
documentation pass are complete. Zero source code has been written. The next
move is to start Phase 0 (core framework skeleton) per `docs/roadmap.md`.

## Next single step

When the next Claude Code session starts, follow this:

1. Read `/CLAUDE.md`, `docs/design.md`, `docs/roadmap.md`, all of
   `docs/decisions/`, and `docs/plugins.md`. Internalize the framework-first
   model.
2. Create `docs/worklog/2026-MM-DD-phase0-skeleton.md` from `TEMPLATE.md`
   and start logging.
3. Fill in `pyproject.toml` `dependencies` with the planned set in
   `docs/design.md §11` (`fastapi`, `uvicorn[standard]`, `httpx[http2]`,
   `pydantic`, `pydantic-settings`, `structlog`, `typer`,
   `sqlalchemy[asyncio]`, `aiosqlite`, `alembic`, `python-ulid`, `keyring`,
   `pynacl`).
4. Verify `pip install -e ".[dev]"` runs clean.
5. Stop there and complete the first checkpoint: worklog + STATUS + commit.

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
