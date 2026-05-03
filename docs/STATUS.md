# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-03 (Claude Code; Phase 0 checkpoint 1 — deps installed)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 0 — core framework skeleton (in progress)
- **Active task**: FastAPI catch-all route + httpx SSE transparent forwarding (Tee)

## Active worklog

`docs/worklog/2026-05-03-phase0-skeleton.md`

## Recent commits

```
b43d82d deps: fill in pyproject.toml runtime dependencies for Phase 0
1c0bf63 docs: translate to English and integrate engineering principles
5231e3f docs: add session-resume infrastructure for cutoff resilience
2202434 docs: pivot to framework-first architecture with plugin model
9ad6e88 docs: lock central server stack and add git auto-commit convention
```

## Where we paused

Phase 0 checkpoint 1 complete: `pyproject.toml` dependencies filled in,
`.venv` (Python 3.12) created, `pip install -e ".[dev]"` verified clean.
No source code written yet beyond empty `__init__.py` stubs.

## Next single step

Phase 0 checkpoint 1 is done. Next: implement the FastAPI catch-all proxy route
and httpx SSE transparent forwarding with Tee (roadmap.md Phase 0 checklist item 2).

Concretely:
1. Create `src/llm_tracker/proxy/` package.
2. FastAPI app with a catch-all route that forwards to `api.anthropic.com` via
   `httpx.AsyncClient.stream()`.
3. Tee: split the SSE stream — pass-through to client, copy to internal buffer.
4. Verify end-to-end with a `respx` mock: request in → SSE chunks out → no delay.
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
