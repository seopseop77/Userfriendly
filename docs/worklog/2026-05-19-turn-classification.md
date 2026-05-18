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

## What's left / known limits

- **Apply migration 0014 to live Supabase** — same procedure as 0013
  (`mcp__supabase__execute_sql` with one atomic `BEGIN; ... COMMIT;`
  block that runs the 5 `ALTER TABLE ADD COLUMN` + 2 `CREATE INDEX` +
  the alembic ledger bump).
- **Backfill the existing 56 rows** (incl. the 36 from 5/19 the
  classifier was developed against). Walk in `created_at` order and
  apply the same classifier + chain-lookup offline. The plugin only
  populates from new INSERTs forward.
- **`fly deploy`** to ship the updated plugin so production
  `analytics_sink` writes populate the new columns going forward.
  Prior image will keep INSERTing with the old (12-column) shape — the
  new columns just stay NULL until redeploy.
- **No FK on `conversation_id`.** Pointing at `id` within the same
  table would create a self-reference; not worth it given the chain
  lookup already covers the integrity question.
- **Edge case unmeasured**: a real Anthropic SDK request where
  `messages[-1].content` is `[]` (empty array) — classifier currently
  returns `tool_continuation`. None observed in the dataset.

## Handoff

The next session should:

1. Apply migration 0014 against the live Supabase project (operator's
   approval — present the SQL first; do not auto-apply per CLAUDE.md §4).
2. Run the backfill — walk all `plugin_analytics` rows ordered by
   `created_at`, compute `classify_request` + the chain-lookup
   `conversation_id` per row, `UPDATE` in place.
3. Verify the backfill produces the conversation grouping documented at
   the top of this worklog (5/19 should yield 3 conversations on the
   main Claude Code session + 2 isolated `claude-manage` probes).
4. `fly deploy` from `main` so the running plugin starts populating the
   columns on every new exchange.

## Suggestions (untouched)

- The classification's prefix list (`_SYNTHETIC_WRAPPER_PREFIXES`) is
  derived from Claude Code's current text wrappers. If Anthropic changes
  the wrapper format, the rule rots silently — consider adding a
  `messages_json` re-scan job that flags rows whose `turn_kind` would
  change with the current rules.
