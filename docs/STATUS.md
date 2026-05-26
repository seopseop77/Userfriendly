# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-05-26

## Active worklog

`docs/worklog/2026-05-26-per-exchange-turn-delta.md`

## Recent commits (last 5)

- `<pending>` docs: backfill 121276a hash in worklog + STATUS
- `121276a` analytics_sink: ADR-0038 per-exchange schema
- `ac61a46` docs: ADR-0038 per-exchange turn delta (proposed)
- `6822dc2` docs: backfill 937f6d1 hash in worklog + STATUS
- `937f6d1` analytics_sink: fix title_gen list-shape classify

## Where we paused

**ADR-0038 delivered and applied live.** `conversation_messages`
and the `plugin_analytics_with_messages` helper view are retired;
per-exchange turn deltas now live directly on `plugin_analytics` in
three new columns:

- `role` (text, ADR-0038 4-value vocab: `user_input` / `title_gen`
  / `tool_result` / `sidecar`) replaces `turn_kind`.
- `request_jsonb` (jsonb) stores `messages[-1].content` with
  session-opener wrappers stripped; no `{role, content}` envelope.
- `system_prompt_jsonb` (jsonb) stores `request.system` only when
  it differs from the conversation's most recent non-null stored
  system (first exchange or variation).

`response_json` (text) cast + renamed to `response_jsonb` (jsonb).
`n_messages_at_request` dropped. `classify_message` /
`split_first_message` (the per-message classifier surface of
ADR-0037) retired in favour of one role per exchange.

ADR-0036, ADR-0037: Status `Superseded by ADR-0038`.

- Live migration applied via Supabase MCP `execute_sql`:
  - ADD COLUMN role / request_jsonb / system_prompt_jsonb.
  - DROP VIEW plugin_analytics_with_messages.
  - ALTER + RENAME response_json → response_jsonb.
  - UPDATE backfill of request_jsonb + role from
    conversation_messages.
  - DROP COLUMN turn_kind, n_messages_at_request.
  - DROP TABLE conversation_messages.
  - UPDATE alembic_version → `0019_per_exchange_turn_delta`.
- Final state: 16 rows / 0 missing role / 0 missing request_jsonb.
  role distribution: user_input 3 / title_gen 2 / tool_result 5 /
  sidecar 6. `system_prompt_jsonb` NULL on all historic rows (raw
  bodies not retained — forward writes populate).
- Tests: 53 pkg / 275 repo / ruff clean.

## Next single step

**Operator deploys updated plugin code to fly (`llm-tracker-server`).**
The new schema is live but the production proxy still runs the
ADR-0036 code path, which writes to columns + tables that no longer
exist. Until deploy, `analytics_sink.insert_failed` will appear in
structlog for every new exchange; the proxy itself stays healthy
(plugin failures are caught defensively).

After deploy, send one exchange through the proxy and confirm a row
lands with `role` and `request_jsonb` populated.

---

## Inactive tracks

**scope_guard** — paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031)
but no live smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

**Participant-#1 install** — back-burner, waits on signup-app redeploy.
See ADR-0035 follow-up in `docs/worklog/2026-05-25-uv-tool-install.md`.
