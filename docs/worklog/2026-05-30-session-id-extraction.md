# 2026-05-30 · Capture Claude Code session id on plugin_analytics

**Author**: Claude Code
**Session trigger**: User asked whether sub-agents getting a different
`conversation_id` than their parent is a problem. After confirming
(a) the client session id is available on the wire and (b) sub-agents
share the parent's session id, user said: "do the session id extraction
first, then we decide the next step based on the result."
**Related docs**: `docs/design.md` (Open issues §"Session
identification"), ADR-0036 (conversation grouping), ADR-0040.

## Interpretation

Step 1 only: **extract and store** the session id. No change to
conversation grouping (`conversation_id` derivation stays the
hash-based ADR-0036 (B) rule). Folding session id into the grouping
key is a separate, ADR-level decision deferred until we see real
captured data.

## Investigation (why this is implementable)

Captured real Claude Code traffic against a local mock to see what is
on the wire (CC 2.1.158, `POST /v1/messages?beta=true`):

- **Session id is present in two places**:
  - Header `x-claude-code-session-id: <uuid>` (raw, clean).
  - Body `metadata.user_id` = a JSON **string**:
    `{"device_id", "account_uuid", "session_id"}`.
- **Sub-agents share the parent's session id.** Spawned a real
  sub-agent (mock returned an `Agent` tool_use); the sub-agent's own
  request carried the *same* `session_id` / `x-claude-code-session-id`
  as the parent, even though only the parent was given `--session-id`.
  There is no `isSidechain`/`parentUuid` structured field on the wire —
  the shared session id is the link signal.

Chose `metadata.user_id` (request body) over the header: the
analytics-sink plugin already receives the body, so no core proxy
change is needed to pass headers through. Stored on the plugin-owned
`plugin_analytics` table, not core `exchanges` (§9 / ADR scope avoided).

## What was done

- Created `packages/llm_tracker_server/alembic/versions/0022_plugin_analytics_session_id.py`
  — adds nullable `session_id TEXT` to `plugin_analytics` (forward-only,
  no backfill; downgrade drops it). (commit 907f95f)
- Modified `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py`
  — added `_session_id_from_request()` (parses `metadata.user_id` JSON,
  returns `session_id` or None), added `session_id` to `_INSERT_SQL`
  and to `_build_row`. (commit 907f95f)
- Modified `packages/llm_tracker_plugin_analytics_sink/tests/test_analytics_sink.py`
  — 2 new tests (extraction from a real-shaped payload; None when
  metadata absent / user_id opaque) + locked `session_id` into the
  INSERT-shape test. (commit 907f95f)

### Step 2 — session-scoped grouping (ADR-0041)

Operator verified the two load-bearing facts on real sessions
(sub-agent shares parent `session_id`; `--resume` after exit in a new
window preserves it), so step 2 was implemented in the same session.

- Created `docs/decisions/0041-session-scoped-conversation-grouping.md`
  — composite (session_id, first_msg_hash) grouping; NULL session_id
  falls back to ADR-0036 hash-only via `IS NOT DISTINCT FROM`. (commit 25539f8)
- Modified `.../analytics_sink/plugin.py` — `_PREV_BY_HASH_SQL` gains
  `AND session_id IS NOT DISTINCT FROM :session_id`;
  `_resolve_conversation` takes + binds the row's `session_id`. No
  migration (column from 0022; existing
  `idx_plugin_analytics_first_msg_hash` covers the query). (commit 25539f8)
- Modified test file — 3 ADR-0041 tests (chain-lookup binds session_id;
  binds None when absent; SQL carries the predicate). (commit 25539f8)

## Decisions

- **Extract from `metadata.user_id`, not the `x-claude-code-session-id`
  header**: body is already available to the plugin; header would force
  a core change. Robust parse (missing metadata / non-JSON / opaque
  user_id → None) so non-CC clients are unaffected.
- **Store on `plugin_analytics`, grouping unchanged**: minimal,
  reversible, no ADR needed (plugin-owned table). Grouping-key change
  is the deferred step 2.
- **No view rebuild**: `plugin_analytics_with_messages` (0021) froze
  `pa.*` at creation, so ADD COLUMN neither breaks nor surfaces it.
  `session_id` is read from the base table.
- **Session-scoped grouping (ADR-0041)**: composite (session_id,
  first_msg_hash) chain-lookup. NULL session_id → `IS NOT DISTINCT
  FROM` falls back to ADR-0036 hash-only (no regress for non-CC /
  historic traffic). No new migration — column + index already exist.
  Full rationale + options in ADR-0041.

## Verification

```
$ ruff format <changed paths> && ruff check <changed paths>
All checks passed!

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_analytics_sink -q
77 passed in 0.24s    (was 72; +5 across step 1 + ADR-0041)

$ alembic -c packages/llm_tracker_server/alembic.ini heads
0022_plugin_analytics_session_id (head)   # single head, chain intact
```

Mocked unit tests only — the engine mock returns canned chain-lookup
results, so the session-scoping *SQL semantics* (different session_id ⇒
no inherit) are not exercised by pytest; they are verified live at
deploy. Reverted an unrelated `ruff format` change to
`scripts/backfill_display_role_vocab.py` (out of scope), twice.

## What's left / known limits

- **Not yet applied to fly.** Migration 0022 (`session_id` column) +
  ADR-0040 + ADR-0041 (logic) all activate on the next operator
  deploy. Until then: no non-null `session_id`, old grouping live.
- Header path (`x-claude-code-session-id`) left unused; metadata path
  suffices. `account_uuid` / `device_id` present but not captured.
- Session-scoping SQL behavior verified only by mocked unit tests +
  reasoning; needs one live confirmation post-deploy.

## Handoff

Step 1 (capture) + step 2 (ADR-0041 session-scoped grouping) both
code-complete + tested (mocked), 77 pass. **Next single step**:
operator deploys `llm-tracker-server` to fly (`alembic upgrade head`
applies 0022), then verify in Supabase on a real session that:
1. parent + sub-agent rows **share one `session_id`** with **distinct
   `conversation_id`s**;
2. two sessions opening with the *same first message* now get
   **separate `conversation_id`s** (the A-1 / r020 collision is gone);
3. resume across windows keeps one `conversation_id`.

## Suggestions (untouched)

- Surface `session_id` in `plugin_analytics_with_messages` + build the
  session-level rollup queries (cost/drift across an agent tree). The
  column is on the base table today; the view still froze `pa.*`.
