# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-03 (Cowork; ADR-0003 sealed, Phase 1a unblocked)
**Updated by**: Claude Cowork

## Current phase

- **Phase**: Phase 1a — plugin SDK (not yet started)
- **Active task**: None — ADR-0003 sealed; Phase 1a ready to start.

## Active worklog

None active. Phase 0 worklog is closed at
`docs/worklog/2026-05-03-phase0-skeleton.md`. Phase 1a should start a new
worklog: `docs/worklog/<YYYY-MM-DD>-phase1a-sdk.md`.

## Recent commits

```
<latest>  docs: revise and accept ADR-0003 (distribution + repo layout)
7e46032   docs: Phase 0 CLOSED — latency PASS, Phase 1a next
dd3686a   proxy: strip Content-Encoding from upstream response headers
594ad32   proxy: instrument first-token latency; add report script
df422d8   proxy: strip Accept-Encoding to prevent ZlibError on client
```

## Where we paused

Phase 0 fully closed (latency PASS; median 0.0 ms, n=20). ADR-0003 is now
sealed (Accepted, 2026-05-03) with the framework + plugin distribution
model: monorepo with per-package `pyproject.toml` (uv workspace), per-
package hatchling build, git URL install during demo phase, PyPI deferred.
Phase 1a is unblocked.

## Next single step

Begin Phase 1a. The first sub-task is the **repository layout migration**
mandated by ADR-0003, before any new SDK code is written:

1. Open a new worklog `docs/worklog/<YYYY-MM-DD>-phase1a-sdk.md`.
2. Migrate the repo to the layout described in ADR-0003 §Decision (1):
   - Create `packages/llm_tracker/` and move existing core into it.
   - Create `packages/llm_tracker_plugin_hello_world/` and move that plugin
     into it.
   - Create `packages/llm_tracker_server/` and move the server stub into
     it.
   - Add a workspace-root `pyproject.toml` with
     `[tool.uv.workspace.members]` listing all `packages/*`.
   - Each package gets its own `pyproject.toml` (hatchling).
3. Verify `uv sync` produces a clean editable install of all packages and
   the existing test suite still passes.
4. Checkpoint: commit + worklog + STATUS update (CLAUDE.md §5.3).

Then the SDK content itself (Phase 1a proper):

5. Create `packages/llm_tracker_sdk/` with `BasePlugin`, `@hook` decorator,
   capability token vocabulary, hook return types (`Pass`, `Block`,
   `Transform`, `Abort`), `plugin.toml` Pydantic schema + validator, test
   harness (mock HookContext, mock EgressGuard, mock SQLite session).
6. Refactor core (`packages/llm_tracker/`) to depend on
   `llm_tracker_sdk` for these interface types — *not the other way
   around* — and ensure plugins do not import `llm_tracker.*` directly.
7. Expand `docs/plugins.md` from skeleton to actual SDK reference.
8. Each step is its own checkpoint.

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
