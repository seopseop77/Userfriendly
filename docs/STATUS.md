# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-05-25

## Active worklog

`docs/worklog/2026-05-25-conversation-grouping-fix.md`

## Recent commits (last 5)

- `<pending>` docs: backfill 354d2e2 hash in STATUS + worklog
- `354d2e2` analytics_sink: ADR-0036 backfill script + applied
- `e391822` docs: backfill 7cf83f3 hash in STATUS + worklog
- `7cf83f3` analytics_sink: canonical grouping (ADR-0036)
- `a96d095` docs: backfill 2b73b4c hash in STATUS + worklog

## Where we paused

**ADR-0036 fully delivered.** Code patch + backfill applied to live
Supabase. The three defects (split conv on `<session>` sidecar,
silent loss on UPSERT collision, ambiguous `role=user`) are all
resolved forward and the historic rows are repaired.

- Backfill applied via Supabase MCP `execute_sql` in three stages
  (A: 151 role rows, B: 155 hashes, C: 14 conv merges incl. one
  3-way). Final state: 34 distinct conversations across both
  tables, no orphans, no rows left with the old `user` role.
- The investigation conv `01KSEVGY6FT6655DN0J708VPTD` (was the
  `<session>` sidecar twin) now holds the full 9-message "너무
  반가워" main flow. msg_index 0 is the real user turn (was the
  `<session>` placeholder). msg_index 4 is *still* the SUGGESTION
  sidecar — that's the operator's lost "현재 mcp 리스트?" turn,
  which cannot be backfilled because the original request body is
  gone. Forward writes are protected.
- Backfill script committed at
  `packages/llm_tracker_plugin_analytics_sink/scripts/backfill_canonical_grouping.py`
  for future re-runs. Dual-mode: `--emit-sql` (default) or
  `--apply` against `LLMTRACK_DATABASE_URL`. Also accepts
  `--from-json` for offline runs.

## Next single step

**Operator's choice.** ADR-0036 is closed. Two outstanding tracks:

1. (back-burner) Participant-#1 install — see ADR-0035 follow-up
   in `docs/worklog/2026-05-25-uv-tool-install.md`. Owner: operator;
   waits on signup-app redeploy.
2. (paused) scope_guard live smoke — still at `0c1ca9d`, separate
   owner. Do not auto-resume.

---

## Inactive tracks

**scope_guard** — paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031)
but no live smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`
