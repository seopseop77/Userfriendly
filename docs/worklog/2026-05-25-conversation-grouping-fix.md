# 2026-05-25 · Conversation grouping fix (canonical hash + priority UPSERT + role vocab)

**Author**: Claude Code
**Session trigger**: Operator inspected conversation `01KSEVH1XVKBCH6GX1Y00P4WS9`
(2026-05-25 06:00–06:03 UTC) and asked three questions that surfaced three
related defects: (1) `<session>` sidecar splits the session into a separate
`conversation_id`; (2) the real user "current MCP list please" turn was
silently dropped; (3) `role=user` does not distinguish typed input from
framework-synthesised continuations. After diagnosis the operator
authorised "전부 수정해줘" with a follow-up that `role` should reuse
`turn_kind` vocabulary (avoid a parallel naming axis).
**Related docs**: ADR-0036 `0036-canonical-conversation-grouping.md`,
ADR-0032 `0032-conversation-messages-dedup.md` (Candidate 1 origin),
worklog `2026-05-19-turn-classification.md` (B-rule origin),
worklog `2026-05-19-candidate-1-handoff.md` (normalization rules).

## Interpretation

Operator opened the session asking about live data; investigation
showed all three issues share the same root cause shape (sidecars and
real turns sharing the same `(conversation_id, msg_index)` keyspace
with no priority distinction). ADR-0036 bundles the three fixes:
(E) canonical user-text hash, (P) priority UPSERT, (V) per-message
origin vocabulary on `role`. Operator's clarification on (V) — reuse
`turn_kind` values plus an `assistant` addition — was confirmed before
implementation so the per-message and per-exchange axes share one
vocab.

Backfill scope: full (operator chose option A on the question
"백필 범위"). Helper view `plugin_analytics_with_messages` lets the
backfill recompute hashes without the dropped `messages_json` column.

## What was done

- Created `docs/decisions/0036-canonical-conversation-grouping.md` —
  three-part decision (E + P + V) with options analysis (commit `7cf83f3`).
- Opened this worklog (commit `7cf83f3`).
- Modified
  `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/classifier.py`:
  added `MessageOrigin` literal, `OVERWRITABLE_ROLES` constant,
  `_SESSION_WRAP_RE`, helpers `_canonical_user_text` and
  `_last_real_user_text`, rewrote `_hash_first_message` over canonical
  user text, refactored rule 6 to share the helper, added public
  `classify_message(msg)` (commit `7cf83f3`).
- Modified
  `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py`:
  imported `classify_message`, swapped `ON CONFLICT DO NOTHING` for
  priority `DO UPDATE ... WHERE` (real-content arrivals displace
  `internal_subprompt`/`claude_manage_probe` placeholders), call
  `classify_message` to write per-message origin role (commit `7cf83f3`).
- Modified
  `packages/llm_tracker_plugin_analytics_sink/tests/test_classifier.py`:
  imported `classify_message`, added 11 new tests covering canonical
  hash collision (sidecar ↔ main flow), wrapper-stripping stability,
  per-message classifier across all five origin shapes (commit `7cf83f3`).
- Modified
  `packages/llm_tracker_plugin_analytics_sink/tests/test_analytics_sink.py`:
  updated `test_normalization_applied_at_upsert_boundary` for new role
  vocab, added `test_upserts_carry_per_message_origin_roles` and
  `test_upsert_sql_uses_priority_do_update` (commit `7cf83f3`).

- Created
  `packages/llm_tracker_plugin_analytics_sink/scripts/backfill_canonical_grouping.py`
  — dual-mode backfill (`--emit-sql` default, `--apply` for direct
  execution via `LLMTRACK_DATABASE_URL`; also accepts `--from-json`
  for offline runs). Reuses `_canonical_user_text` and
  `classify_message` from the package so the backfill cannot drift
  from the runtime logic. Operator-confirmed go-ahead given;
  applied directly via Supabase MCP `execute_sql` against the live
  DB in this session (commit `<pending>`).
- Applied ADR-0036 backfill against live Supabase:
  - **Stage A** (role reclass): 253 conversation_messages rows ->
    `assistant=102 / internal_subprompt=35 / tool_continuation=68 /
    user_input_turn_start=48`. Zero rows remain with old `user`
    vocab.
  - **Stage B** (hash recompute): 155 plugin_analytics rows updated
    to the canonical user-text hash. Distinct hash count 48 -> 34.
  - **Stage C** (conversation merge): 14 loser convs merged into
    their `<session>` ↔ main-flow pair winners. One 3-way merge
    (`01KS06FVZ9...`). Priority UPSERT correctly displaced
    `internal_subprompt` placeholders with `user_input_turn_start`
    real content (notably msg_index 0 of the investigation conv
    `01KSEVGY...` is now the real "너무 반가워" main-flow
    bundle, not the `<session>` wrap).
  - Final counts: 34 distinct conversations in both tables; no
    orphans (pa <-> cm); 231 conversation_messages rows (was 253;
    -22 from sidecar placeholders replaced + 3-way merger
    DISTINCT-ON dedup).
  - C1 first attempt failed: Postgres rejects multiple incoming
    rows competing for the same `ON CONFLICT` slot within a single
    statement (the 3-way merger collision). Fix: pre-deduplicate
    via `DISTINCT ON (winner_conv, msg_index)` with priority-aware
    ORDER BY so only the highest-priority incoming row hits the
    UPSERT. Applied successfully on retry.

## Decisions

- **(V) Reuse `turn_kind` vocab for `role`** instead of inventing
  `user_typed`/`tool_result`/`synthetic_user`/`assistant`. One vocab
  across the schema, single classifier source, natural joins.
  Operator confirmed mid-session.
- **(P) Priority UPSERT via `DO UPDATE ... WHERE`** instead of dropping
  sidecars from `conversation_messages` entirely (option 3 in ADR-0036).
  Keeps sidecar content visible for debugging; the `WHERE` clause
  enforces that only `internal_subprompt` rows can be replaced.
- **No DDL change**: `role` stays a `text` column; the migration is the
  Python backfill, not a schema change.

## Verification

Code patch unit tests (analytics_sink package, full project):

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_analytics_sink/tests/ -q
.....................................................                    [100%]
53 passed in 0.15s

$ .venv/bin/python3.12 -m pytest -q
...275 passed, 31 skipped in 6.08s

$ .venv/bin/python3.12 -m ruff format packages/llm_tracker_plugin_analytics_sink/ \
    && .venv/bin/python3.12 -m ruff check packages/llm_tracker_plugin_analytics_sink/
5 files reformatted, 2 files left unchanged
All checks passed!
```

Targeted new-test highlights (see `test_classifier.py` and
`test_analytics_sink.py` for full list):

* `test_first_msg_hash_session_sidecar_matches_main_flow` — the
  `<session>` sidecar (string content) and the main flow (list
  content with leading wrappers) now produce **identical**
  `first_msg_hash`, so the chain-lookup `(B) rule` folds them into one
  `conversation_id`. Repro for the original investigation case.
* `test_upsert_sql_uses_priority_do_update` — pins the
  `DO UPDATE ... WHERE` SQL contract at the plugin layer (real
  content displaces sidecar placeholders; real content never
  displaced by sidecars).
* `test_upserts_carry_per_message_origin_roles` — a mixed
  five-message array (user-typed + assistant + tool_result +
  SUGGESTION sidecar + user-typed follow-up) produces one distinct
  origin role per index.

Live-DB post-backfill verification (Supabase MCP execute_sql):

```
remaining_old_user:  0
distinct_roles:      4  (assistant, internal_subprompt,
                         tool_continuation, user_input_turn_start)
pa_distinct_convs:   34
cm_distinct_convs:   34
pa_orphans:          0
cm_orphans:          0
```

Investigation conv `01KSEVGY6FT6655DN0J708VPTD` (post-merge) — the
"너무 반가워" session — now contains all 9 messages of the original
main flow under the unified conversation_id:

* msg 0  user_input_turn_start  (system-reminder + "너무 반가워")
* msg 1  assistant              "안녕! 반가워 😊..."
* msg 2  user_input_turn_start  "이모지 안 쓰기로 언제 한거야?"
* msg 3  assistant              (thinking + emoji rule answer)
* msg 4  internal_subprompt     [SUGGESTION MODE: ...] — see limit
* msg 5  assistant              (thinking + `claude mcp list` Bash)
* msg 6  tool_continuation      MCP server health check
* msg 7  assistant              "현재 연결된 MCP 서버 목록이야:..."
* msg 8  internal_subprompt     [SUGGESTION MODE: ...]

## What's left / known limits

- **Real user input lost at original write time is NOT recoverable.**
  Investigation conv msg_index 4 still shows the SUGGESTION
  placeholder; the operator's actual "현재 mcp 리스트 알려줘" turn
  was dropped by the old `ON CONFLICT DO NOTHING` policy and only
  the LLM API response (msg_index 5-7) survived. The forward fix
  prevents this for new traffic; the backfill cannot resurrect a
  message whose request body is no longer in
  `conversation_messages`.
- `classify_message` does not emit `claude_manage_probe`. The five-
  value vocabulary is reserved for parity with `TurnKind`; the rare
  offline-probe case (list content with `<session>` last text and no
  CC system signature) classifies as `user_input_turn_start` at
  per-message scope because system_text is unavailable. Acceptable
  per the ADR (rare in production; analyst joins
  `plugin_analytics.turn_kind` for the exchange-level distinction
  when needed).
- The backfill ran via Supabase MCP `execute_sql` rather than the
  committed Python script. Functional equivalent (same canonical
  hash function imported into Python computation; same priority
  UPSERT clause translated to SQL), but a re-run for verification
  would invoke the script via `LLMTRACK_DATABASE_URL` against a
  copy of the DB.

## Handoff

ADR-0036 fully delivered: code patch + backfill applied + worklog
post-mortem. Resume tasks beyond this scope (e.g. participant-#1
install — see ADR-0035 follow-up in
`docs/worklog/2026-05-25-uv-tool-install.md`).

If a new investigation of historic conversations is needed, the
post-backfill state is:

* 34 distinct conversation_ids across plugin_analytics and
  conversation_messages (down from 48 / 75 respectively pre-fix).
* `role` carries per-message origin everywhere (`user` is no longer
  a valid value); join `cm.role = pa.turn_kind` is now meaningful.
* `<session>` ↔ main-flow pairs are unified; the 14 collapse pairs
  are documented above.
