# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-05-27

## Active worklog

`docs/worklog/2026-05-27-rls-operator-tables-fix.md`

(Three previously open operator-side tracks all closed and verified
live this session — see "Where we paused" below. Active worklog points
at the most recently closed narrative for context; no work is in
flight.)

## Recent commits (last 5)

- `<pending>` docs: backfill c599d08 hash in worklog + STATUS
- `c599d08` docs: close three operator-side tracks
- `65e0839` docs: backfill c4e695d hash in worklog + STATUS
- `c4e695d` storage: fix RLS 0020 to grant llm_tracker_app policies
- `2cd100e` docs: backfill 496e517 hash in worklog + STATUS
- `496e517` agent: release v0.1.3 (typer.Exit catch hotfix)

## Where we paused

Quiet point. The three deferred operator tracks finished and were
verified via Supabase MCP + git remote checks in this session:

1. **RLS 0020 smoke** — this session itself is proxied through fly
   under the rewritten policies; the auth middleware writes land
   without 403. See worklog "Operator follow-through (2026-05-27)".
2. **`agent/v0.1.3` push** — `c786a5b` tag on the remote;
   `origin/main..HEAD` empty. Operator-side reinstall + smoke owned
   by the operator. See
   `docs/worklog/2026-05-27-claude-manage-passthrough-args.md`
   "Operator follow-through (2026-05-27)".
3. **ADR-0038 deploy + backfill** — `leftover_title_gen=0`,
   `leftover_user_input_string=0`, 35 rows; fresh `<session>` opener
   at 06:43Z landed as `role='sidecar'` array. See
   `docs/worklog/2026-05-26-vocab-and-collapse-refinement.md`
   "Operator follow-through (2026-05-27)".

## Next single step

**Wait for the next operator request.** No track is mid-flight.

The one documented small follow-up still on the board is the
**WebFetch wrapper prefix**: `"\nWeb page content:\n---\n…"` was
observed once but deliberately not added to the prefix list yet —
the plan was to batch it with the next discovery. Pick it up when
either (a) another framework auto-call prompt is spotted, or (b)
the operator wants to clear the backlog. Owning file:
`packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/classifier.py`
(prefix list). Add the prefix, add a fixture row to the classifier
tests, then a one-liner UPDATE to reclassify any historic rows that
match.

---

## Inactive tracks

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
