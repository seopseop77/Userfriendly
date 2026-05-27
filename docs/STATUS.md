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

`docs/worklog/2026-05-27-restore-reconstruction-view.md`

(ADR-0039 + migration 0021 — restored `plugin_analytics_with_messages`
view atop ADR-0038's per-exchange delta schema. Main-flow only; new
`system_prompt_resolved` column. Live-applied via Supabase MCP;
alembic ledger at `0021_restore_messages_view`. Tests + ruff clean.)

## Recent commits (last 5)

- `<pending>` analytics: restore plugin_analytics_with_messages view (ADR-0039)
- `5bf88ff` docs: backfill d1e8ae4 hash in worklog + STATUS
- `d1e8ae4` analytics_sink: register WebFetch wrapper prefix
- `b4aaaee` docs: backfill c599d08 hash in worklog + STATUS
- `c599d08` docs: close three operator-side tracks

## Where we paused

View restored and verified against live data. Two test conversations
exercised — 12-row main-flow (perfect A/B/A/B alternation, n_msgs =
2k+1) and 11-row mixed (sidecars correctly excluded with
`messages_jsonb IS NULL`, no count pollution).

## Next single step

**Operator deploys `llm-tracker-server` to fly** to activate the
WebFetch wrapper prefix added in the prior commit (`d1e8ae4`):

```
fly deploy -c packages/llm_tracker_server/fly.toml
```

Same step that was outstanding before this view-restore work — the
view doesn't depend on or block it. After deploy, send one
WebFetch-bearing exchange through and confirm it lands as
`role='sidecar'` (or stays `user_input` with the WebFetch block
stripped from `request_jsonb` if accompanied by user-typed text).

If the operator wants to keep going on this repo instead of touching
fly, there is no documented next item — wait for the next request.

---

## Inactive tracks

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
