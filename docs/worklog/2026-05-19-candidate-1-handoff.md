# 2026-05-19 · Candidate-1 (conversation_messages dedup) implementation handoff

**Author**: Claude Code (handoff — *no code in this session*).
**Audience**: the next Claude Code session that picks up this track.
**Status**: design + data analysis complete; implementation pending.
**Session trigger**: "다음 세션에서 후보 1 구현할 수 있도록 충분한
정보를 제공하는 문서만 작성하고 다음 세션에서 수행할게."

This document is **self-contained**. The next session can resume from
this file alone — it carries the *why*, the *what*, the *how*, and
the *verify* in one place. No need to re-derive anything from the
prior conversation.

## 1. What we agreed to build

A row-per-message dedup table that eliminates the
quadratic-on-conversation-length duplication in
`plugin_analytics.messages_json`. The current shape stores the
entire message history on every row of a tool chain — a 9-step
chain duplicates `messages[0]` (the giant `<system-reminder>` block)
9 times, `messages[1]` 8 times, and so on. For the 5/19 stress
session (1 conv, 12 main-flow + 4 internal_subprompt + subagent
rows) we measured a **4.8× duplication factor**, climbing
quadratically: a 17-step chain saves ~9×, a 30-step chain ~16×.

### Design name & previous decision
This is "Candidate 1" from the 2026-05-19 design discussion. The
operator picked it over "Candidate 2 — row-level delta with
parent_id" because UPSERT-by-`(conversation_id, msg_index)` is
**idempotent and resilient to streaming retries**: a same-index
re-insert with a slightly-different body silently keeps the first
arrival rather than corrupting or duplicating data. Candidate 2's
chain-walk recovery is brittle by comparison.

### What stays on `plugin_analytics`
- `id`, `exchange_id`, `org_id`, `created_at` (row identity)
- `model_requested`, `model_served`, `response_json` (per-row data)
- `input_tokens`, `output_tokens`, `cache_read_tokens`,
  `cache_write_tokens`, `stop_reason` (per-row metrics)
- `turn_kind`, `turn_seq`, `slash_commands`, `first_msg_hash`,
  `conversation_id` (classification — unchanged from migration 0014)

### What moves
- `messages_json` (text, ~200 KB/row average) **→ dropped** at the
  end of the migration.

### What is added
- `conversation_messages` table, keyed by `(conversation_id, msg_index)`.
- `plugin_analytics.n_messages_at_request` (int) — replaces
  `messages_json` as the lookup pointer.
- `plugin_analytics_with_messages` view — convenience join.

## 2. Schema — migration 0015

File path: `packages/llm_tracker_server/alembic/versions/0015_conversation_messages.py`.
Use the same atomic `BEGIN ... COMMIT` pattern as 0013 and 0014.

```sql
-- 1) New table
CREATE TABLE conversation_messages (
    conversation_id  text        NOT NULL,
    msg_index        integer     NOT NULL,
    org_id           uuid        NOT NULL REFERENCES orgs(id),
    role             text        NOT NULL,         -- 'user' | 'assistant'
    content_jsonb    jsonb       NOT NULL,         -- normalized (see §3)
    first_seen_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (conversation_id, msg_index)
);
CREATE INDEX conversation_messages_org_conv_idx
    ON conversation_messages (org_id, conversation_id);
-- RLS posture matches plugin_analytics (operator-tooling-only).
-- Don't enable RLS; document the choice next to the 0007 docstring
-- precedent in the migration's module-top comment.

-- 2) New column
ALTER TABLE plugin_analytics
    ADD COLUMN n_messages_at_request integer;

-- 3) Backfill (see §5) -- run BEFORE the column drop below.

-- 4) Drop the old column (per user direction
--    "messages_json은 후보 1 구현할 때 drop하는 걸로 하고")
ALTER TABLE plugin_analytics DROP COLUMN messages_json;

-- 5) Helper view (re-creatable from canonical data)
CREATE VIEW plugin_analytics_with_messages AS
SELECT
    pa.*,
    (SELECT jsonb_agg(
        jsonb_build_object('role', cm.role, 'content', cm.content_jsonb)
        ORDER BY cm.msg_index
     )
     FROM conversation_messages cm
     WHERE cm.conversation_id = pa.conversation_id
       AND cm.msg_index < pa.n_messages_at_request
    ) AS messages_jsonb
FROM plugin_analytics pa;

-- 6) Alembic ledger
UPDATE alembic_version SET version_num = '0015_conversation_messages';
```

Downgrade path: reverse order. The `messages_json` re-creation isn't
fully possible after data loss, so downgrade should re-add the
column as `text NULL` and leave a NOTICE. We don't expect to ever
downgrade in production.

## 3. Normalization spec (data-confirmed 2026-05-19)

Confirmed by the STRESS-1 ~ STRESS-6 single-session stress run
(main conv `01KS084X32YARSRKGBY35ACRYM`, hash `6e48b5c55a29`,
KST 22:52–22:56). Two — and only two — dynamic fields broke
byte-level prefix identity across same-conversation rows:

### Rule A — drop `cache_control` (every content block)
Prompt-caching breakpoints move between rows. Already known from
the prior session's row-comparison work.

### Rule B — collapse single-text-block array to bare string
Anthropic SDK / Claude Code serialises a user message
`[{"type":"text","text":"X"}]` on the **first** send, then re-sends
the same message as bare string `"X"` on every subsequent turn.
Verified directly:

| Row | `messages[2].content` |
|---|---|
| n=3 (just after STRESS-2 sent) | `[{"text":" [STRESS-2] 그걸 5로 곱하면?", "type":"text"}]` |
| n=5, n=7, ... (later turns) | `" [STRESS-2] 그걸 5로 곱하면?"` |

After both rules, prefix comparison across the main conv rows
becomes **fully consistent** (verified n=9 ↔ n=11 ↔ n=13 ↔ ...
all `prefix_equal_after_strip = true`).

### Other fields verified **stable** (do **not** normalise)
Verified by direct equality after Rules A+B for the same content
block across rows:

- `tool_use.id` (echoed back from response — stable)
- `tool_result.tool_use_id` (stable)
- `thinking.signature` (extended-thinking signature, stable in
  observed STRESS-4 / STRESS-6 data — the
  `ErcCClkIDR...` value at idx 7 was identical between n=9 and n=11)

### Reference implementation
Add a new module
`packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/normalize.py`:

```python
"""Canonicalise an Anthropic Messages API message for dedup
(conversation_messages table). See
docs/worklog/2026-05-19-candidate-1-handoff.md §3 for the
empirical derivation of these two rules."""

from __future__ import annotations
from typing import Any

_DROPPED_BLOCK_KEYS: frozenset[str] = frozenset({"cache_control"})


def canonical_message(m: dict[str, Any]) -> dict[str, Any]:
    """Return the (role, content) form used as the canonical key
    in conversation_messages.content_jsonb."""
    role = m.get("role")
    content = _canonical_content(m.get("content"))
    return {"role": role, "content": content}


def _canonical_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return content
    blocks = [_drop_dropped_keys(b) for b in content if isinstance(b, dict)]
    # Rule B: a single bare text block collapses to the bare string.
    if (
        len(blocks) == 1
        and blocks[0].get("type") == "text"
        and set(blocks[0].keys()) == {"type", "text"}
    ):
        return blocks[0]["text"]
    return blocks


def _drop_dropped_keys(block: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in block.items() if k not in _DROPPED_BLOCK_KEYS}
```

Unit tests (path: `tests/test_normalize.py`):

- `test_drops_cache_control_from_every_block` — array of 3 blocks,
  middle one has `cache_control` → middle block emerges without
  `cache_control`, others untouched.
- `test_collapses_single_text_block_to_string` — input
  `[{"type":"text","text":"hi"}]` → output `"hi"`.
- `test_keeps_multi_block_arrays` — array with text + tool_use →
  stays as array (no collapse).
- `test_keeps_array_when_single_text_has_extra_keys` —
  `[{"type":"text","text":"x","cache_control":...}]` → after
  dropping cache_control, has only `{type,text}` → collapse OK.
  Edge: this is the same as the previous case after Rule A. Cover
  explicitly so the order-of-application is documented.
- `test_string_content_passthrough` — `"hi"` stays `"hi"`.
- `test_tool_use_block_id_preserved` —
  `[{"type":"tool_use","id":"toolu_X","name":"Read","input":{...}}]`
  → all fields preserved verbatim.
- `test_tool_result_block_tool_use_id_preserved` — same for
  tool_result.
- `test_thinking_signature_preserved` —
  `[{"type":"thinking","thinking":"","signature":"ErcCClkIDR..."}]`
  → signature preserved.

## 4. Plugin write path

File: `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py`.

### Current state after commit `f0c591b`
- `_INSERT_SQL` writes 17 placeholders into `plugin_analytics`
  including `messages_json` and casts `slash_commands` to jsonb.
- `_build_row` carries `messages_json` from the raw request body.
- `_resolve_conversation` runs `_PREV_BY_HASH_SQL` (which now
  returns only `conversation_id`) and `_LAST_SEQ_IN_CONV_SQL`
  (MAX(turn_seq) form) — both already (B)-rule-compliant.

### Changes
1. Drop `messages_json` from `_INSERT_SQL` placeholders; add
   `n_messages_at_request`. Keep everything else as-is.
2. In `_build_row`, replace `messages_json` with
   `n_messages_at_request: len(messages)`.
3. Add a new helper `_UPSERT_MESSAGE_SQL` that runs once per message
   in the request body, BEFORE the row INSERT:

```python
_UPSERT_MESSAGE_SQL = sa.text(
    """
    INSERT INTO conversation_messages
        (conversation_id, msg_index, org_id, role, content_jsonb)
    VALUES
        (:conversation_id, :msg_index, :org_id, :role,
         CAST(:content_jsonb AS jsonb))
    ON CONFLICT (conversation_id, msg_index) DO NOTHING
    """
)
```

4. In `on_persisted`, after `_resolve_conversation` returns
   `(conv_id, turn_seq)`:

```python
parsed_messages = parsed.get("messages") or []
for idx, m in enumerate(parsed_messages):
    norm = canonical_message(m)
    await conn.execute(
        _UPSERT_MESSAGE_SQL,
        {
            "conversation_id": conv_id,
            "msg_index": idx,
            "org_id": ctx.org_id,
            "role": norm["role"] or "",
            "content_jsonb": json.dumps(norm["content"], ensure_ascii=False),
        },
    )
# ... then the row INSERT, with n_messages_at_request=len(parsed_messages)
```

Important sequence: messages UPSERTs MUST run *before* the row
INSERT but inside the same `engine.begin()` transaction — the row
references the conversation by `conversation_id` and downstream
analytics joining the view must see the messages before they see
the row. The existing `async with self._engine.begin() as conn`
gives us this for free.

### Existing test impact
- `test_row_written_on_persisted_with_parsed_response` asserts
  `params["messages_json"] == body.decode("utf-8")`. **Remove**
  that assertion; **add** assertions on the messages UPSERTs:
  the AsyncMock conn.execute will have been called once per
  message with the conversation_id, msg_index, and the normalised
  content_jsonb.
- `test_missing_parsed_response_writes_nulls` similarly: remove
  any messages_json reference; the row still writes (now with
  `n_messages_at_request` set).
- `test_persist_fallback_recovers_when_body_arrives_late` — the
  body-recovery path stays; just confirm the messages UPSERTs use
  the late-arrival body.
- `test_slash_commands_bound_as_json_string_not_python_list` —
  unchanged.
- Add `test_messages_upserted_one_per_index` — request with 3
  messages should produce 3 UPSERT calls with msg_index 0, 1, 2,
  in order.
- Add `test_normalization_applied_at_upsert_boundary` —
  single-text-block array in the input → `content_jsonb`
  parameter is a JSON-encoded bare string.

## 5. Backfill plan

Run as part of migration 0015 via a `DO $$ ... $$` PL/pgSQL block
or as a follow-up `execute_sql` step. Either works; the cleaner
form is a single `INSERT ... SELECT ... ON CONFLICT DO NOTHING`
post-table-create, BEFORE the column drop:

```sql
INSERT INTO conversation_messages
    (conversation_id, msg_index, org_id, role, content_jsonb, first_seen_at)
SELECT
    pa.conversation_id,
    (m_idx - 1)::int                                AS msg_index,
    pa.org_id,
    COALESCE(m->>'role', '')                        AS role,
    -- canonicalisation in SQL:
    --   Rule A: strip cache_control from every block when content is array
    --   Rule B: collapse single bare {type:text,text:X} array to "X"
    CASE
      WHEN jsonb_typeof(m->'content') <> 'array'
        THEN m->'content'
      ELSE (
        CASE
          WHEN jsonb_array_length(
                 (SELECT jsonb_agg(blk - 'cache_control')
                  FROM jsonb_array_elements(m->'content') blk)
               ) = 1
           AND ((SELECT jsonb_agg(blk - 'cache_control')
                  FROM jsonb_array_elements(m->'content') blk) -> 0 ->> 'type')
                = 'text'
           AND (SELECT jsonb_object_keys(
                  (SELECT jsonb_agg(blk - 'cache_control')
                   FROM jsonb_array_elements(m->'content') blk) -> 0
                ) ORDER BY 1 LIMIT 1) = 'text'  -- exactly 2 keys check below
          THEN
            to_jsonb(
              (SELECT (blk - 'cache_control') ->> 'text'
               FROM jsonb_array_elements(m->'content') blk
               LIMIT 1)
            )
          ELSE (SELECT jsonb_agg(blk - 'cache_control')
                FROM jsonb_array_elements(m->'content') blk)
        END
      )
    END                                              AS content_jsonb,
    pa.created_at                                    AS first_seen_at
FROM plugin_analytics pa
   , jsonb_array_elements((pa.messages_json::jsonb)->'messages')
       WITH ORDINALITY t(m, m_idx)
ON CONFLICT (conversation_id, msg_index) DO NOTHING;

UPDATE plugin_analytics pa
SET n_messages_at_request = jsonb_array_length((pa.messages_json::jsonb)->'messages');
```

⚠ The SQL Rule-B form is awkward because PG doesn't make
"single-text-block-with-only-type-and-text-keys" easy to express
in a CASE. **Safer alternative**: do the Python normalisation in a
short one-off script (run from the next session's environment via
asyncpg) that walks `plugin_analytics` and INSERTs into
`conversation_messages`. The script reuses
`canonical_message()` from §3 so we never have two diverging
implementations of the rule.

Backfill order:
1. Create table + column.
2. **Backfill** (Python script via asyncpg or the SQL above).
3. Verify: `SELECT COUNT(*) FROM conversation_messages` matches
   `SUM(jsonb_array_length((messages_json::jsonb)->'messages'))`
   from `plugin_analytics`.
4. Verify a few specific rows survive the round-trip — see §6
   "Verification rows".
5. Drop `messages_json`.

## 6. Verification rows (the round-trip oracle)

After backfill, these queries must return the listed values.

### V1 — main stress conv: 12 unique messages
```sql
SELECT COUNT(*) FROM conversation_messages
WHERE conversation_id = '01KS084X32YARSRKGBY35ACRYM';
-- expect: 23 (max n_msgs in that conv was 23, indices 0..22)
```

### V2 — Rule B collapsed the user STRESS-2 message to a string
```sql
SELECT content_jsonb FROM conversation_messages
WHERE conversation_id = '01KS084X32YARSRKGBY35ACRYM' AND msg_index = 2;
-- expect: a JSON string ("...") -- not an array
-- exact value contains "[STRESS-2] 그걸 5로 곱하면?"
```

### V3 — Rule A removed cache_control from messages[0]
```sql
SELECT
  jsonb_typeof(content_jsonb) AS shape,
  EXISTS (
    SELECT 1
    FROM jsonb_array_elements(content_jsonb) blk
    WHERE blk ? 'cache_control'
  ) AS has_cache_control
FROM conversation_messages
WHERE conversation_id = '01KS084X32YARSRKGBY35ACRYM' AND msg_index = 0;
-- expect: shape=array, has_cache_control=false
```

### V4 — joined view reconstructs the original message list shape
```sql
SELECT jsonb_array_length(messages_jsonb) AS n_msgs
FROM plugin_analytics_with_messages
WHERE conversation_id = '01KS084X32YARSRKGBY35ACRYM'
ORDER BY created_at DESC
LIMIT 1;
-- expect: 23 (matching n_messages_at_request of the last row)
```

### V5 — total messages saved
```sql
-- Pre-dedup duplication count (for the savings report):
SELECT SUM(n_messages_at_request) AS total_message_writes_old_schema
FROM plugin_analytics
WHERE conversation_id = '01KS084X32YARSRKGBY35ACRYM';
-- expect: 100+ (1+3+5+7+...+23 over the 12 rows)

-- Post-dedup actual storage:
SELECT COUNT(*) AS distinct_messages
FROM conversation_messages
WHERE conversation_id = '01KS084X32YARSRKGBY35ACRYM';
-- expect: 23 (matches the longest message array length)
```

The ratio is the dedup savings — should land near 5× for this
conversation, more for longer chains.

## 7. Touched files (full list)

```
Create
  packages/llm_tracker_server/alembic/versions/0015_conversation_messages.py
  packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/normalize.py
  packages/llm_tracker_plugin_analytics_sink/tests/test_normalize.py

Modify
  packages/llm_tracker_server/src/llm_tracker_server/storage/models.py
    + ConversationMessage ORM model (mirror migration 0015 columns)
    - remove `messages_json` Column from PluginAnalytics
    + add `n_messages_at_request` Column

  packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py
    + import canonical_message from .normalize
    + _UPSERT_MESSAGE_SQL constant
    ~ _INSERT_SQL: drop :messages_json, add :n_messages_at_request
    ~ _build_row: same change in parameter dict
    ~ on_persisted: insert messages first, then the analytics row,
      in one transaction

  packages/llm_tracker_plugin_analytics_sink/tests/test_analytics_sink.py
    - remove messages_json assertions
    + n_messages_at_request assertions
    + messages-UPSERT call-count + per-call shape assertions

  docs/STATUS.md
    + new top entry summarising the migration

Drop (in the same migration)
  plugin_analytics.messages_json (column)
```

## 8. Risk register

- **R1: live row during deploy** — if a new exchange lands between
  step 2 (backfill) and step 5 (column drop), it writes a fresh
  `messages_json`. The migration is atomic at the column level, so
  the column drop will succeed once no in-flight transactions hold
  it. Plugin code post-deploy doesn't write `messages_json`
  anyway. Acceptable.
- **R2: orphan messages on conversation_id rewrite** — the (B)
  rule never rewrites a conversation_id post-INSERT, so this can't
  happen.
- **R3: normalization rule drift** — Python (`normalize.py`) vs
  backfill SQL must produce identical canonical content. Mitigate
  by running backfill *through* the Python function (one-off
  script over asyncpg), not via the SQL form. Lift the SQL form to
  a documented fallback only.
- **R4: large conversations on the helper view** — the view
  re-aggregates messages each query. For a 23-message conv this
  is trivial; for hypothetical 200+ message conversations it
  starts to matter. Not in scope for this migration; revisit if a
  conv ever exceeds 100 messages.
- **R5: backwards-incompatible column drop** — any external
  consumer of `plugin_analytics.messages_json` breaks. Operator
  confirmed this is intentional ("후보 1 구현할 때 drop하는
  걸로 하고"). No known external consumer today.

## 9. ADR decision

This is a public-schema change (drops a column other systems could
have been reading). CLAUDE.md §9 lists `plugin_analytics` schema
under public interfaces requiring an ADR. **Open ADR-0032 for
this** at the start of the next session, with this worklog as the
context section:

```
docs/decisions/0032-conversation-messages-dedup.md
Title: Dedup plugin_analytics message bodies into conversation_messages
Status: Accepted (or Proposed if any open questions remain)
Context: §1 of this worklog
Decision: §2-3 of this worklog
Consequences: §8 + the §5 V5 savings ratio
Open questions: §8 R3 mitigation choice (Python script vs SQL)
```

ADR can be one short page since the worklog carries all the
detail.

## 10. Pre-commit posture

Same as commit `f0c591b`:

```
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_sdk \
    packages/llm_tracker_plugin_analytics_sink \
    packages/llm_tracker_server -q
expect: ~155 passed (+ 8 new normalize tests, +2-3 plugin tests),
        18 skipped (unchanged)

$ .venv/bin/python3.12 -m ruff check packages/
expect: All checks passed!

$ alembic upgrade --sql head    (round-trip the new migration)
expect: clean BEGIN/SQL/COMMIT block
```

## 11. Handoff sequence the next session should follow

1. Read this file end-to-end. Read commit `f0c591b` summary to
   confirm the (B) rule + scrubber fix are deployed.
2. Open ADR-0032 (per §9) using this worklog as the context dump.
   Mark Accepted if no fresh questions.
3. Implement in this order:
   - `normalize.py` + `test_normalize.py` first (pure functions).
     Get tests green.
   - Migration 0015 SQL file. Round-trip alembic upgrade/downgrade
     `--sql` locally.
   - ORM model updates in `storage/models.py`.
   - Plugin INSERT path change + test updates.
   - Run the affected package test suite. Expect ~155 passed.
3. Apply migration 0015 to Supabase via MCP `execute_sql`
   (matches the 0013 / 0014 precedent — one atomic
   `BEGIN ... COMMIT`).
4. Run the backfill **via a one-off Python script** that imports
   `canonical_message` and uses asyncpg. Don't ship the script;
   keep it inline in the worklog for the day. ~117 historic rows
   + however many new ones since the STRESS run.
5. Verify §6 V1–V5 against live data.
6. **Drop `messages_json`** from `plugin_analytics`.
7. Commit. Then ask operator for `fly deploy`.
8. After `fly deploy`, hit the proxy once and confirm the new
   write path lands a fresh `conversation_messages` row + a
   `plugin_analytics` row with `n_messages_at_request` set.

## 12. Out of scope (intentional)

- Re-classifying historic `turn_kind` or `conversation_id`.
  Already done in commit `f0c591b`.
- Migrating `response_json` to a dedup table. The data shows it
  doesn't duplicate across rows of the same conversation (each row
  has its own assistant response). Leave on `plugin_analytics`.
- ADR-level re-think of `plugin_analytics` RLS posture. Still
  queued under STATUS §"Queued follow-ups".
- Subagent (Task tool) conversation handling. STRESS-6 confirmed
  it lands as a separate `conversation_id` automatically (different
  `first_msg_hash` because the haiku-model subagent has its own
  `messages[0]`). No design change needed.
