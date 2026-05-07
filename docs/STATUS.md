# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-07 (`claude-manage` wrapper + async cleanup — code complete, manual e2e pending)
**Updated by**: Claude Code

## Current phase

- **Phase**: Pre-Phase-1c side-quest #2 — `claude-manage` wrapper. Phase 1b sealed at 75ff46a; Phase 1c (`scope_guard`) still on deck.
- **Active task**: User-facing CLI ergonomics — typing `claude-manage` auto-starts the proxy daemon, sets `ANTHROPIC_BASE_URL`, runs `claude`, and tears the proxy down on last-user exit (refcounted via `fcntl.flock`).

## Active worklog

`docs/worklog/2026-05-07-claude-manage.md`

## Recent commits

```
9aa8321   cli: async cleanup so claude-manage exits instantly
d2e33d5   cli: claude-manage wrapper auto-starts proxy
faa718d   chore: add .omc to .gitignore
55e55cd   docs: worklog + STATUS for test-only plugin verification
2c28f68   plugins: TEST-ONLY token_counter + keyword_block
```

## Where we paused

**`claude-manage` wrapper code-complete.** New top-level console script
(`packages/llm_tracker/src/llm_tracker/cli/manage.py`) that:

- Probes whether the configured proxy is up; if not, spawns
  `python -m llm_tracker start ...` as a detached daemon (own session,
  stdout+stderr to `var/proxy.log`, PID to `var/proxy.pid`).
- Acquires a shared `fcntl.flock` on `var/proxy.lock` as a refcount
  across concurrent `claude-manage` invocations.
- Spawns `claude <argv>` as a foreground child with
  `ANTHROPIC_BASE_URL` pointed at the proxy. Wrapper ignores
  SIGINT/SIGQUIT (Ctrl-C reaches `claude` directly); SIGTERM/SIGHUP
  to the wrapper are forwarded to `claude`.
- On `claude` exit, attempts a non-blocking exclusive lock upgrade. If
  successful (no other `claude-manage` alive), forks a detached
  cleanup child (`_spawn_async_cleanup`) that runs SIGTERM → poll →
  SIGKILL on the proxy. **The wrapper itself returns immediately** so
  the user's shell prompt isn't gated on uvicorn shutdown. The lock
  fd is inherited by the cleanup child; concurrent `claude-manage`
  invocations still block on `LOCK_SH` until the child exits,
  preserving the "no traffic to a shutting-down proxy" invariant.
  Pid file absent ⇒ proxy was started outside the wrapper (e.g.
  manual `llm-tracker start`) ⇒ left alone.

23 new unit tests; full suite **173 passed**, ruff clean on the new
files. `uv sync` registers both `claude-manage` and `llm-tracker`
console scripts. `python -m llm_tracker ...` works via a new
`__main__.py` (used by the daemon spawn path).

**Pre-Phase-1c verification (2026-05-06) still applies** — the
TEST-ONLY plugins (`token_counter`, `keyword_block`) remain loaded
and ready for the long-deferred manual e2e against real Anthropic
traffic.

Closed-checkpoint roll-up (cleanup pass A–G + both stop gates):

- A (e2ee4f0): EgressGuard wired into proxy lifespan
- B (3010aae): signature verifier wired + signing CLI
- C (a2bc3d4): on_persisted ordering fix
- D (b1724fa): synthetic SSE block response
- E (2891e8f): audit_log append-only triggers
- F (6a08c9c): ADR-0008 housekeeping
- G (96305e1): session_factory property + ADR-0009
- 14 (654fbfb): ADR-0010 retroactive (Block/Abort.plugin)
- 15 (cfbbb8e): ADR-0011 Transform policy
- 16 (bbb33e7): Transform impl + 4 tests
- 17 (4606ed0): ADR-0012 hook payload routing
- 18 (75ff46a): HookContext impl + 14 tests
- pre-1c verification (2c28f68): TEST-ONLY token_counter + keyword_block

### Phase 1b loose ends

Known-deferred; each would be its own checkpoint when picked up:

- `end_exchange` cleanup in the forwarder (Block/Abort early
  returns + `generate()` finally). Bounded leak only.
- Per-level shape refinement of `ctx.request_text()` (L1 hash,
  L2 scrubbed) — wired in Phase 1c alongside scrubbers.
- Manifest `min_content_level` field — Phase 1c when scope_guard
  needs it.
- Response-side ctx accessors — wait for Extractor / structured
  response data.

## Next single step

Two paths, pick one:

1. **Manual real-traffic e2e via `claude-manage`** — in a fresh
   working directory, run `.venv/bin/llm-tracker init`, then
   `.venv/bin/claude-manage --print "hello"` (or any quick claude
   command). Verify `var/proxy.log` shows clean uvicorn startup, the
   exchange lands in `var/llm_tracker.db`, the token-counter sidecar
   db (`var/plugin_token_counter.db`) records usage, and the proxy
   process is gone after `claude` exits. This combines the previously
   pending Phase-1a/1b manual e2e with the new wrapper's smoke test.
2. **Open Phase 1c — `scope_guard` plugin.** Create
   `docs/worklog/<YYYY-MM-DD>-phase1c-scope-guard.md`, point this
   STATUS.md at it, and schedule removal of the now-redundant
   `keyword_block` test plugin in that worklog.

Both `keyword_block` (Phase 1c overlap) and `token_counter` (Phase 2
Extractor overlap) are explicit throwaways — track their removal
when the proper replacement lands.

## Blocking / decisions needed

- None.

## Progress

- [x] Design v0.1 written
- [x] Framework pivot v0.2
- [x] English-only documentation pass
- [x] ADRs 0001–0008 sealed (0004 superseded by 0007)
- [x] Phase 0 — core skeleton (CLOSED 2026-05-04)
- [x] Phase 1a — plugin SDK (CLOSED 2026-05-05)
- [x] Phase 1b — security boundary hardening (CLOSED 2026-05-06)
- [x] Pre-Phase-1c verification — TEST-ONLY plugins (token_counter, keyword_block) (2026-05-06, commit 2c28f68)
- [x] `claude-manage` wrapper — auto-spawn proxy + lifecycle-coupled cleanup (2026-05-07, commits d2e33d5, 9aa8321)
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
