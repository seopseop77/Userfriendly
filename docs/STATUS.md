# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-03 (Claude Code; latency instrumentation done — awaiting user's 10+ prompts)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 0 — core framework skeleton (e2e verified; latency measurement in progress)
- **Active task**: User runs 10+ prompts through proxy → run report script → record PASS/FAIL

## Active worklog

`docs/worklog/2026-05-03-phase0-skeleton.md`

## Recent commits

```
594ad32 proxy: instrument first-token latency; add report script
df422d8 proxy: strip Accept-Encoding to prevent ZlibError on client
f27b0d7 docs: Phase 0 code-complete — worklog + STATUS final update
e123092 feat: EgressGuard skeleton, BasePlugin interface, hello_world plugin
e4cda64 docs: checkpoint 4 — CLI + PluginHost done, next EgressGuard + hello_world
```

## Where we paused

Latency instrumentation committed (594ad32). Waiting for user to run 10+
prompts through the proxy, then will execute the report script and record
PASS/FAIL in the worklog.

## Next single step

**User action required**: run the proxy and send 10+ natural prompts through it.

```bash
# Terminal 1 — boot proxy
mkdir -p var
.venv/bin/llm-tracker start > var/proxy.log 2>&1 &

# Terminal 2 (or normal Claude Code terminal)
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
# Use Claude Code as normal for 10+ prompts, then say "done"
```

After user says "done": kill proxy (SIGTERM), run report script, record result.

## Blocking / decisions needed

- None for starting Phase 0.
- Before entering Phase 1, ADR-0003 (distribution) must be updated to
  reflect the framework + plugin split. Not blocking now.

## Progress

- [x] Design v0.1 written
- [x] Framework pivot v0.2
- [x] ADRs 0001–0007 sealed (0004 superseded by 0007)
- [x] English-only documentation pass
- [~] Phase 0 — core skeleton (code-complete; manual e2e pending)
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
