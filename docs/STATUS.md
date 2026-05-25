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

- `<pending>` docs: backfill 7cf83f3 hash in STATUS + worklog
- `7cf83f3` analytics_sink: canonical grouping (ADR-0036)
- `a96d095` docs: backfill 2b73b4c hash in STATUS + worklog
- `2b73b4c` signup: inline style for pre no-wrap (CDN class insufficient)
- `f55d18b` docs: backfill 2b4f573 hash in STATUS + worklog

## Where we paused

**Three coupled defects in `conversation_messages` / `plugin_analytics`
fixed in code (ADR-0036). Backfill of historic rows pending operator
review.**

- Trigger: operator inspected conv `01KSEVH1XVKBCH6GX1Y00P4WS9`
  (2026-05-25 06:00–06:03 UTC) and surfaced three issues that share
  one root cause (sidecars and real turns sharing the
  `(conversation_id, msg_index)` keyspace with no priority):
  1. `<session>` session-classify sidecar split into a separate
     `conversation_id` from the main flow even though they shared
     the same user-typed text.
  2. The user's real "현재 mcp 리스트?" turn was silently dropped by
     `ON CONFLICT DO NOTHING` because an earlier SUGGESTION sidecar
     had already filled `msg_index=4`.
  3. `role=user` did not distinguish typed input from
     framework-synthesised continuations.
- Fix (ADR-0036, three parts shipped together):
  - **(E)** `first_msg_hash` now hashes the canonical user-typed
    text (strips `<session>...</session>` wrap, skips
    `<system-reminder>` / `<local-command-*>` / `<command-*>`
    wrappers). The `<session>` sidecar and the main flow share a
    hash → share a `conversation_id` via the (B) chain-lookup.
  - **(P)** `conversation_messages` UPSERT changed from
    `DO NOTHING` to `DO UPDATE ... WHERE`: stored
    `internal_subprompt`/`claude_manage_probe` placeholders can be
    overwritten by `user_input_turn_start`/`tool_continuation`/
    `assistant` arrivals. Real content never displaced by sidecars.
  - **(V)** `conversation_messages.role` now carries the
    per-message *origin* (`turn_kind` vocab + `assistant`) via the
    new `classify_message` classifier instead of the raw API role.
- Tests: 53 in `analytics_sink/tests/` and 275 in the full project,
  all green. `ruff format && ruff check` clean.

## Next single step

**Write the ADR-0036 backfill script and run its dry-run report
against the live Supabase DB, then review with operator before apply.**

Path: `packages/llm_tracker_plugin_analytics_sink/scripts/backfill_canonical_grouping.py`
(to be created). Dry-run by default; reports: hash changes,
conversation_id remap diffs (especially the
`01KSEVGY...` ↔ `01KSEVH1...` collapse), role reclassification
counts, PK-collision merge cases under the priority rule. Apply
only after operator OK.

---

## Inactive tracks

**scope_guard** — paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031)
but no live smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`
