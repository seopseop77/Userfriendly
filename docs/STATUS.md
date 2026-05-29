# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-05-30

## Active worklog

`docs/worklog/2026-05-28-headless-subsession-probe.md`

(Interactive slash probe `s001` (2026-05-29) found the post-`/compact`
turn orphaning into the global empty-text conversation bucket
`01KSJC53…` — Suggestion #8. **Fixed by ADR-0040**: `first_msg_hash`
scans past wrapper-only leading messages (resume marker) to the first
real user message; None → own conversation_id. Result doc:
`docs/experiments/headless-subsession/results/2026-05-29-s001-interactive-slash.md`.
Sink tests + ruff clean, 72 pass.)

## Recent commits (last 5)

- `<pending>` docs: backfill 0d20585 hash in STATUS
- `0d20585` analytics-sink: scan past wrapper messages for grouping hash (ADR-0040)
- `f8f43d0` docs: drop runner-interactive.sh, inline the command
- `e5ee423` docs: headless probe campaign results + slash runbook
- `1f04b2e` docs: backfill 2b69a72 hash in worklog

## Where we paused

ADR-0040 implemented and tested (forward-only, no migration —
`first_msg_hash` column already nullable). The fix closes the
`/compact` orphaning. Not yet deployed to fly; live behavior still
shows the old empty-bucket merge until deploy.

## Next single step

**Operator deploys `llm-tracker-server` to fly** to activate ADR-0040
(and the still-pending WebFetch prefix from `d1e8ae4`):

```
fly deploy -c packages/llm_tracker_server/fly.toml
```

After deploy, verify with an interactive `/compact` + 2–3 follow-up
messages (runbook `INTERACTIVE-SLASH.md`): the post-compact turns
should now share one fresh `conversation_id` (not `01KSJC53…`), and a
text-less request should get `first_msg_hash IS NULL`.

---

## Inactive tracks

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
