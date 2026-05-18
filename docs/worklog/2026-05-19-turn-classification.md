# 2026-05-19 · plugin_analytics turn classification (migration 0014)

**Author**: Claude Code
**Session trigger**: User wanted to identify exactly which `exchanges` /
`plugin_analytics` rows correspond to a human-typed prompt (vs. Claude
Code's internal tool-result continuations, `/compact` summarize calls,
`[SUGGESTION MODE]` autocomplete probes, and `claude-manage` probes).
**Related docs**: `docs/design.md`, migration 0007 (`plugin_analytics`),
migration 0013 (most recent schema cleanup).

## Interpretation

The user wanted a deterministic way to:

1. Find the `plugin_analytics` row for every human-typed prompt across a
   Claude Code session, including after `/clear` and `/compact`.
2. Group exchanges into "conversations" (the same accumulated `messages[]`
   history) — natural boundaries are `/clear`, `/compact`, and process
   restart.
3. Number exchanges within a single turn so a turn that fans out into N
   tool-result rounds can be reconstructed in order.

Multi-turn analysis on the 36 captured rows from 5/19 (00:06–00:21 KST)
established the classification grammar — see "Decisions" below. The
chosen approach lives in the existing `plugin_analytics` plugin rather
than core `exchanges`, because the rules are derived from request body
structure and may evolve; the plugin owns its own table and can backfill
from `messages_json` whenever the rules change.

## What was done

- Created `packages/llm_tracker_server/alembic/versions/0014_analytics_turn_classification.py`
  — adds five nullable columns to `plugin_analytics`:
  `turn_kind`, `turn_seq`, `slash_commands` (JSONB), `first_msg_hash`,
  `conversation_id`; plus indexes
  `idx_plugin_analytics_first_msg_hash (first_msg_hash, created_at DESC)`
  and `idx_plugin_analytics_conversation (conversation_id)`.
- Created `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/classifier.py`
  — pure `classify_request(parsed_body) -> Classification` returning
  `(turn_kind, slash_commands, first_msg_hash, n_messages)`. Rules walk
  the last user message's content blocks from the end, skipping Claude
  Code's synthesised wrapper text (`<system-reminder>`,
  `<command-*>`, `<local-command-*>`, post-compact resume marker), and
  classify on what's left. `first_msg_hash` is SHA-256[:16] of the
  concatenated text of `messages[0]` — `cache_control` metadata is
  deliberately excluded so caching toggles don't invalidate identity.
- Modified `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py`
  — `on_persisted` now (a) computes a `Classification` from the parsed
  request, (b) runs a chain-lookup `SELECT` for the most recent row with
  the same `first_msg_hash` in the same org, (c) decides
  `conversation_id` by comparing `n_messages` (inherit if growing,
  mint new if equal/smaller — handles identical-first-prompt collision
  after `/clear` or restart), (d) seeds `turn_seq` via a second `SELECT`
  for the latest non-NULL `turn_seq` in the resolved conversation.
- Created `packages/llm_tracker_plugin_analytics_sink/tests/test_classifier.py`
  — 15 unit tests covering every observed shape from the 5/19 dataset
  (session resume, mid-conversation follow-up, tool-result continuation,
  `/compact` summarize, `[SUGGESTION MODE]`, `claude-manage` probe,
  slash command extraction, hash stability across history growth,
  cache_control invariance, string-content normalisation, empty-messages
  defensive path, frozen-dataclass guarantee).
- Modified `packages/llm_tracker_plugin_analytics_sink/tests/test_analytics_sink.py`
  — updated `_fake_engine` to model the SELECT-before-INSERT shape,
  added `_insert_params` helper that locates the INSERT among multiple
  `execute` calls, plus two new tests: `tool_continuation` inherits a
  prior row's `conversation_id` with `turn_seq` incremented;
  identical-first-prompt-after-clear mints a new `conversation_id`.

## Decisions

- **Columns live in `plugin_analytics`, not core `exchanges`.** Rule
  changes are likely; the plugin can backfill from `messages_json`
  whenever the prefix list or grammar shifts. Keeps `exchanges` (CLAUDE.md
  §9 public interface) untouched.
- **Four labels for `turn_kind`** (`user_input_turn_start` /
  `tool_continuation` / `internal_subprompt` / `claude_manage_probe`)
  rather than further subdividing `internal_subprompt` into
  compact-summarize / suggestion-ghost / etc. Slash commands carried in
  a side column instead. Simpler vocabulary; specialisations can be
  derived from `slash_commands` + `messages_json`.
- **No `parent_conversation_id` link across `/compact`.** Treat each
  post-compact restart as a new conversation. Compact-rate is still
  derivable from `slash_commands @> '["compact"]'`; threading isn't
  worth the schema cost right now.
- **No `client_kind` column.** `claude_manage_probe` already surfaces
  via `turn_kind`; sub-agent classification will get its own follow-up
  if/when the data shows up.
- **`conversation_id` resolution uses chain-lookup, not standalone hash.**
  Naive `hash(messages[0])` collides when the user types the same first
  prompt twice within the same day (the wrapping `<system-reminder>`
  blocks include `currentDate` and `claudeMd` recent-commit context, but
  those don't change between two rapid identical typings). Resolution:
  look up the most recent same-hash row in the same org; if our
  `n_messages > prev.n_messages` we are continuing that conversation,
  else we are starting a new one — store `this_exchange_id` as
  `conversation_id`. Two indexed `SELECT`s per write, well within budget.

## Verification

```
$ .venv/bin/python -m pytest packages/llm_tracker_plugin_analytics_sink/tests/ -q
......................                                                   [100%]
22 passed in 0.13s

$ .venv/bin/python -m pytest \
    packages/llm_tracker_server/tests/ \
    packages/llm_tracker_sdk/tests/ \
    packages/llm_tracker_plugin_analytics_sink/tests/ -q
136 passed, 18 skipped in 5.55s

$ .venv/bin/python -m ruff check --output-format=concise \
    packages/llm_tracker_plugin_analytics_sink \
    packages/llm_tracker_server/alembic/versions/0014_analytics_turn_classification.py
All checks passed!
```

Live DB and backfill **not yet applied** (see Handoff).

## Live apply + backfill (2026-05-19, same session)

Operator authorised steps 1 and 2 (per user direction "1, 2번까지만
해. fly deploy는 내가 따로 할게"). `fly deploy` is owned by the
operator.

**Migration applied** via Supabase MCP `execute_sql` — one atomic
`BEGIN; ... COMMIT;` block ran the 5 `ALTER TABLE ADD COLUMN` + the
2 `CREATE INDEX` + the alembic ledger bump
`0013_schema_cleanup` → `0014_analytics_turn_class`. Post-state
verified: `alembic_version.version_num = '0014_analytics_turn_class'`;
5 new columns present on `plugin_analytics`; both indexes present.

**Backfill applied** via Supabase MCP `execute_sql` — one
`DO $$ ... $$` plpgsql block that ports `classify_request` +
`compute_first_msg_hash` + the chain-lookup logic to SQL, walks
`plugin_analytics` ordered by `(created_at, id)`, and updates the
five new columns per row. SHA-256 uses `extensions.digest(...)`
with `convert_to(text, 'UTF8')` (a direct `text::bytea` cast fails
on rows that contain non-ASCII bytes); wrapper-prefix matching
uses `regexp_replace(t, '^[[:space:]]+', '')` to mirror Python's
`str.lstrip()` (PostgreSQL's bare `ltrim()` only trims spaces).

**Post-backfill distribution** (56 rows total, 18 conversations, 14
user-typed turn starts):

| `turn_kind`            | rows | with `turn_seq` | with `conversation_id` |
|------------------------|-----:|----------------:|-----------------------:|
| `tool_continuation`    |   27 |              27 |                     27 |
| `user_input_turn_start`|   14 |              14 |                     14 |
| `internal_subprompt`   |    9 |               0 |                      9 |
| `claude_manage_probe`  |    6 |               0 |                      6 |

5/19 KST session (36 rows) groups into 4 conversations on the main
Claude Code session + 2 isolated `claude-manage` probes — slightly
finer than the 3-conversation estimate in the original analysis
because the 00:19:35 post-compact attempt streamed-out with
`stop_reason=null` and its retry at 00:20:00 sent a different
`messages[0]` (so they hashed differently and split into two
conversations rather than one). That's the design behaving
correctly — each `messages[0]` defines its own conversation.

Slash command extraction confirmed on the three live cases:
`/compact` rows at 00:19:35 + 00:20:00, `/clear` row at 00:21:07
all carry `slash_commands = '["compact"]'` / `'["clear"]'` as
expected.

## What's left / known limits

- **`fly deploy`** still pending (operator-owned). Until that ships,
  the prior image keeps INSERTing the old 12-column shape; new rows
  in `plugin_analytics` will leave the five new columns NULL until
  redeploy. Old rows (already backfilled) keep their populated
  classification.
- **No FK on `conversation_id`.** Pointing at `id` within the same
  table would create a self-reference; not worth it given the chain
  lookup already covers the integrity question.
- **Edge case unmeasured**: a real Anthropic SDK request where
  `messages[-1].content` is `[]` (empty array) — classifier currently
  returns `tool_continuation`. None observed in the dataset.

## Handoff

Track is now waiting on a single operator step: `fly deploy` from
`main`. After that ships, every new `plugin_analytics` row will
populate the five new columns via the in-process plugin path
exercised by the 22 unit/integration tests in this session, not
via the offline SQL backfill that handled the 56 historic rows.

## Suggestions (untouched)

- The classification's prefix list (`_SYNTHETIC_WRAPPER_PREFIXES`) is
  derived from Claude Code's current text wrappers. If Anthropic changes
  the wrapper format, the rule rots silently — consider adding a
  `messages_json` re-scan job that flags rows whose `turn_kind` would
  change with the current rules.
