# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-04
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1a — plugin SDK (layout migration done; SDK content next)
- **Active task**: Fill `packages/llm_tracker_sdk/` with SDK content.

## Active worklog

`docs/worklog/2026-05-04-phase1a-sdk.md`

## Recent commits

```
66220fb   infra: migrate to uv workspace monorepo (ADR-0003 Phase 1a layout)
9f90d50   docs: revise and accept ADR-0003 (distribution + repo layout)
7e46032   docs: Phase 0 CLOSED — latency PASS, Phase 1a next
dd3686a   proxy: strip Content-Encoding from upstream response headers
594ad32   proxy: instrument first-token latency; add report script
```

## Where we paused

Phase 1a layout migration complete (commit 66220fb). Repo is now a uv
workspace monorepo under `packages/`. `uv sync` installs all packages
editable; 6/6 tests pass; `hello_world` entry_point is discoverable.
`packages/llm_tracker_sdk/` exists as a skeleton only (`__init__.py` stub).

## Next single step

Begin Phase 1a SDK content — fill `packages/llm_tracker_sdk/`:

1. Move `Pass/Block/Transform/Abort` hook return types from
   `packages/llm_tracker/src/llm_tracker/plugin_host/hooks.py` into
   `packages/llm_tracker_sdk/src/llm_tracker_sdk/`.
2. Move `BasePlugin` from `plugin_host/base.py` into SDK; have core import
   from SDK (not define it).
3. Add `@hook("name")` decorator (or plain abstract methods — decide first).
4. Add capability token vocabulary as SDK constants.
5. Add `plugin.toml` Pydantic schema + validator to SDK.
6. Add test harness (mock HookContext, mock EgressGuard, mock SQLite session).
7. Expand `docs/plugins.md` from skeleton to SDK reference.
8. Each step = its own checkpoint.

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
