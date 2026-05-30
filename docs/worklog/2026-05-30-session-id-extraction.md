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

## Verification

```
$ ruff format <changed paths> && ruff check <changed paths>
All checks passed!

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_analytics_sink -q
74 passed in 0.25s    (was 72; +2 new)

$ alembic -c packages/llm_tracker_server/alembic.ini heads
0022_plugin_analytics_session_id (head)   # single head, chain intact
```

Reverted an unrelated `ruff format` change to
`scripts/backfill_display_role_vocab.py` (out of scope).

## What's left / known limits

- **Migration not yet applied to fly.** Like ADR-0040, live activation
  waits on operator deploy. Until then no row has a non-null
  `session_id`.
- Header path (`x-claude-code-session-id`) left unused; metadata path
  is sufficient for Claude Code. `account_uuid` / `device_id` are also
  in the payload but intentionally not captured (out of scope).
- Verified only on headless `claude -p` with an explicit `--session-id`.
  Interactive + `--resume` session-id stability not directly re-captured
  (transcript keys imply it; confirm opportunistically).

## Handoff

Code complete + tested (mocked). **Next single step**: operator deploys
`llm-tracker-server` to fly (`alembic upgrade head` runs there), then
run a short interactive session that spawns a sub-agent and confirm in
Supabase that parent + sub-agent rows share one `session_id` while
keeping distinct `conversation_id`s. **Then return to the user to
decide step 2** (whether to fold `session_id` into the grouping key —
this would fix the r020 / A-1 identical-first-message collision but
reverses ADR-0036's intentional cross-UUID unification, so it needs an
ADR).

## Suggestions (untouched)

- Step-2 ADR candidate: session-scoped conversation grouping vs the
  current global (B) rule. Evidence: campaign r020 (✅ working as
  designed today) and A-1 (`01KSJC53…` cross-UUID sidecar pollution).
