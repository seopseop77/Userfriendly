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

`docs/worklog/2026-05-30-session-id-extraction.md`

(session_id capture (0022) + ADR-0041 session-scoped grouping deployed +
live-verified 2026-05-31. Follow-up: `session_id` now surfaced in the
`plugin_analytics_with_messages` view via migration 0023 — view body
byte-identical to 0021, just re-expanded. Code-complete, awaiting one
more deploy.)

## Recent commits (last 5)

- `<pending>` docs: 0023 view-session_id follow-up worklog/STATUS
- `62f56b3` storage: surface session_id in plugin_analytics_with_messages
- `fbd2da9` docs: close session-id track (deployed + verified)
- `25539f8` analytics-sink: scope conversation grouping by session id (ADR-0041)
- `907f95f` analytics-sink: capture client session id (migration 0022)

## Where we paused

session-id capture + grouping (0022 + ADR-0041) deployed + live-verified
2026-05-31. Follow-up migration **0023** (view exposes `session_id`)
code-complete, ruff clean, single alembic head, view body identical to
0021 — **awaits the next fly deploy** to take effect.

## Next single step

**Operator deploys `llm-tracker-server` to fly** (`alembic upgrade head`
applies 0023):

```
fly deploy -c packages/llm_tracker_server/fly.toml
```

After deploy, spot-check `SELECT session_id FROM
plugin_analytics_with_messages LIMIT 1` returns the column. Then the
track is fully closed (optional rollup queries remain as a Suggestion).

---

## Inactive tracks

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
