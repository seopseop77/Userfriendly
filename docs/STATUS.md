# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-04
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1a — plugin SDK (hook types + BasePlugin done; capability tokens next)
- **Active task**: SDK remaining items — capability tokens, plugin.toml schema, test harness, docs.

## Active worklog

`docs/worklog/2026-05-04-phase1a-sdk.md`

## Recent commits

```
c3b417e   sdk: move hook types and BasePlugin into llm_tracker_sdk
66220fb   infra: migrate to uv workspace monorepo (ADR-0003 Phase 1a layout)
9f90d50   docs: revise and accept ADR-0003 (distribution + repo layout)
7e46032   docs: Phase 0 CLOSED — latency PASS, Phase 1a next
dd3686a   proxy: strip Content-Encoding from upstream response headers
```

## Where we paused

`Pass/Block/Transform/Abort` and `BasePlugin` moved into `llm_tracker_sdk`
(commit c3b417e). Core (`host.py`, `forwarder.py`) now imports from SDK.
Old `plugin_host/hooks.py` and `plugin_host/base.py` deleted from core.
6/6 tests pass; ruff clean.

## Next single step

Continue Phase 1a SDK content:

1. Add capability token vocabulary to SDK as string constants
   (`packages/llm_tracker_sdk/src/llm_tracker_sdk/capabilities.py`).
2. Add `plugin.toml` Pydantic schema + validator to SDK.
3. Add test harness (mock HookContext, mock EgressGuard, mock SQLite session).
4. Expand `docs/plugins.md` from skeleton to SDK reference.
5. Each step = its own checkpoint.

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
