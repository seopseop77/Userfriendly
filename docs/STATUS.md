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
ADR-0041 session-scoped grouping + view exposure — all deployed and
live-verified 2026-05-31).

## Recent commits (last 5)

- `87bc575` docs: fully close session-id track
- `a9a8878` docs: 0023 view-session_id follow-up worklog/STATUS
- `62f56b3` storage: surface session_id in plugin_analytics_with_messages
- `fbd2da9` docs: close session-id track (deployed + verified)
- `25539f8` analytics-sink: scope conversation grouping by session id (ADR-0041)

## Where we paused

session-id track **fully closed** (deployed + live-verified 2026-05-31):
capture (0022), session-scoped grouping (ADR-0041), and `session_id`
exposed in `plugin_analytics_with_messages` (0023). Nothing pending.

## Next single step

No active track — awaiting the next request. Optional follow-up on file
(not started): session-level rollup queries (cost/drift across an agent
tree) on top of the now-exposed `session_id` — see the closed worklog's
Suggestions.

---

## Inactive tracks

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
