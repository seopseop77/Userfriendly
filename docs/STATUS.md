# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b checkpoint 16 — Gate 1 closed)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (cleanup pass A–G + ADR-0010 + Gate 1 closed; Gate 2 next)
- **Active task**: Gate 1 (Transform handling) fully landed (ADR-0011 + impl + 4 tests). Next is Gate 2 — ADR-0012 + HookContext implementation.

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
bbb33e7   proxy: honour Transform from before_forward (ADR-0011)
cfbbb8e   docs: ADR-0011 — Transform handling policy (Gate 1)
654fbfb   docs: ADR-0010 — retroactive ratification of Block/Abort plugin field
bda318c   docs: Phase 1b checkpoint 13 — cleanup pass complete; gates open
96305e1   core: layering polish + manifest allowed_modes tightening
```

## Where we paused

Phase 1b cleanup-pass checkpoint 16 complete (Gate 1 fully
landed). The forwarder now honours `Transform` returns from
`before_forward` per ADR-0011: plugin headers merge into the
request (plugin wins on conflict), `Transform.body` replaces
the upstream body wholesale when not None, and the dispatcher
short-circuits at the first plugin returning a non-`Pass`
result (first-wins). Four respx-driven tests pin each axis
end-to-end against a mocked Anthropic upstream.

118/118 tests pass; touched files lint clean.

Closed-checkpoint roll-up:

- A: EgressGuard wired into proxy lifespan (e2ee4f0)
- B: signature verifier + signing CLI (3010aae)
- C: on_persisted ordering fix (a2bc3d4)
- D: synthetic SSE block response (b1724fa)
- E: audit_log append-only triggers (2891e8f)
- F: ADR-0008 housekeeping (6a08c9c)
- G: session_factory property + ADR-0009 (96305e1)
- 14: ADR-0010 retroactive (654fbfb)
- 15: ADR-0011 Transform policy (cfbbb8e)
- 16: Transform impl + 4 tests (bbb33e7)

Remaining: **Gate 2 — Hook payload routing (ADR-0012, option (b)
HookContext).**

## Next single step

**Write ADR-0012 — Hook payload routing.** Path
`docs/decisions/0012-hook-context.md`. Document option (b):
add a `HookContext` to the SDK; every hook signature gains
`ctx: HookContext`. `ctx` holds `session_id` and `exchange_id`
and exposes lazy accessors (e.g. `ctx.request_text(level=...)`)
that degrade at access time per
`effective_ceiling(mode, user_opted_in=...)`. The
`min_content_level` manifest field stays deferred to Phase 1c.
Commit with scope `docs`. After the ADR commits, define
`HookContext` in the SDK, add the `ctx` parameter to all 8 hook
signatures (BasePlugin + PluginHost dispatchers), update
`hello_world` to accept (and ignore) `ctx`, write tests pinning
ctx propagation and lazy degradation. Each passing test group
is its own checkpoint.

## Blocking / decisions needed

- None. Gate 2 is unblocked; implementation can begin.

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
