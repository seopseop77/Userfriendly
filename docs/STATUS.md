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
id in `metadata.user_id` JSON + an `x-claude-code-session-id` header;
operator confirmed sub-agents share the parent's session id and
`--resume` preserves it. **Step 1**: capture `session_id` into
`plugin_analytics.session_id` (migration 0022). **Step 2 (ADR-0041)**:
scope the (B) chain-lookup by session_id — composite (session_id,
first_msg_hash); NULL falls back to hash-only via `IS NOT DISTINCT
FROM`. Fixes the r020/A-1 identical-opener collision; links
parent↔sub-agents. Sink tests + ruff clean, 77 pass. Prior track:
ADR-0040 `/compact` orphaning fix.)

## Recent commits (last 5)

- `<pending>` docs: ADR-0041 + session-id worklog/STATUS update
- `25539f8` analytics-sink: scope conversation grouping by session id (ADR-0041)
- `907f95f` analytics-sink: capture client session id (migration 0022)
- `3680caa` docs: session-id extraction worklog + STATUS
- `0d20585` analytics-sink: scan past wrapper messages for grouping hash (ADR-0040)

## Where we paused

session_id capture (0022) + session-scoped grouping (ADR-0041) both
code-complete + tested (mocked, 77 pass). ADR-0041 needs no migration
(column from 0022; existing index covers the query). **Three changes
now await the same fly deploy**: ADR-0040 (wrapper scan), 0022 (column
+ extraction), ADR-0041 (grouping logic). Until deploy, old grouping is
live and no row carries a non-null `session_id`.

## Next single step

**Operator deploys `llm-tracker-server` to fly** (`alembic upgrade head`
applies 0022):

```
fly deploy -c packages/llm_tracker_server/fly.toml
```

After deploy, verify in Supabase on a real session: (1) parent +
sub-agent rows **share one `session_id`** with **distinct
`conversation_id`s**; (2) two sessions opening with the same first
message now get **separate `conversation_id`s** (A-1/r020 collision
gone); (3) resume across windows keeps one `conversation_id`; (4)
ADR-0040: post-`/compact` turns share a fresh id (not `01KSJC53…`).

---

## Inactive tracks

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
