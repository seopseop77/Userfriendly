# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-05-31

## Active worklog

_None active._ Last closed:
`docs/worklog/2026-05-30-session-id-extraction.md` (session_id capture +
ADR-0041 session-scoped grouping — deployed + live-verified 2026-05-31).

## Recent commits (last 5)

- `<pending>` docs: close session-id track (deployed + verified)
- `4c30112` docs: ADR-0041 + session-id worklog/STATUS update
- `25539f8` analytics-sink: scope conversation grouping by session id (ADR-0041)
- `907f95f` analytics-sink: capture client session id (migration 0022)
- `0d20585` analytics-sink: scan past wrapper messages for grouping hash (ADR-0040)

## Where we paused

session-id track **closed**. Deployed to fly and live-verified
2026-05-31: parent + sub-agents share one `session_id` with distinct
`conversation_id`s; identical-opener collision (A-1/r020) gone; resume
across windows keeps one `conversation_id`; ADR-0040 post-`/compact`
turns group on a fresh id. No non-null `session_id` on rows predating
the deploy (forward-only, expected).

## Next single step

No active track — awaiting the next request. Optional follow-up on file
(not started): surface `session_id` in `plugin_analytics_with_messages`
and build session-level rollup queries (cost/drift across an agent
tree) — see the closed worklog's Suggestions.

---

## Inactive tracks

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
