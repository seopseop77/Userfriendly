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

`docs/worklog/2026-05-30-session-id-extraction.md`

(Confirmed via live wire capture that Claude Code sends the CLI session
id in `metadata.user_id` JSON + an `x-claude-code-session-id` header,
and that **sub-agents share the parent's session id**. Step 1 done:
extract `session_id` from `metadata.user_id` into a new nullable
`plugin_analytics.session_id` column — grouping unchanged. Sink tests +
ruff clean, 74 pass. Step 2 — folding session_id into the grouping key
— deferred to a future ADR. Prior track: ADR-0040 `/compact` orphaning
fix, see `docs/worklog/2026-05-28-headless-subsession-probe.md`.)

## Recent commits (last 5)

- `<pending>` docs: session-id extraction worklog + STATUS
- `907f95f` analytics-sink: capture client session id (migration 0022)
- `8559f77` docs: backfill 0d20585 hash in STATUS
- `0d20585` analytics-sink: scan past wrapper messages for grouping hash (ADR-0040)
- `f8f43d0` docs: drop runner-interactive.sh, inline the command

## Where we paused

`session_id` extraction code-complete + tested (mocked). Migration 0022
adds the column forward-only (no backfill). **Two changes now await the
same fly deploy**: ADR-0040 (`first_msg_hash` wrapper scan) and 0022
(`session_id` column + extraction). Until deploy, no row carries a
non-null `session_id` and the `/compact` empty-bucket merge persists.

## Next single step

**Operator deploys `llm-tracker-server` to fly** (`alembic upgrade head`
runs there, applying 0022):

```
fly deploy -c packages/llm_tracker_server/fly.toml
```

After deploy, run an interactive session that spawns a sub-agent and
confirm in Supabase: parent + sub-agent rows **share one `session_id`**
while keeping **distinct `conversation_id`s**. Then return to the user
to decide step 2 (session-scoped grouping — needs an ADR; reverses
ADR-0036's cross-UUID unification). Also still pending from ADR-0040:
post-`/compact` turns share a fresh `conversation_id` (not `01KSJC53…`).

---

## Inactive tracks

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
