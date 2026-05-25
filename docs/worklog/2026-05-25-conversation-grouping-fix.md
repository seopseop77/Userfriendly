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
  three-part decision (E + P + V) with options analysis (commit `<pending>`).
- Opened this worklog (commit `<pending>`).
- Modified
  `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/classifier.py`:
  added `MessageOrigin` literal, `OVERWRITABLE_ROLES` constant,
  `_SESSION_WRAP_RE`, helpers `_canonical_user_text` and
  `_last_real_user_text`, rewrote `_hash_first_message` over canonical
  user text, refactored rule 6 to share the helper, added public
  `classify_message(msg)` (commit `<pending>`).
- Modified
  `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py`:
  imported `classify_message`, swapped `ON CONFLICT DO NOTHING` for
  priority `DO UPDATE ... WHERE` (real-content arrivals displace
  `internal_subprompt`/`claude_manage_probe` placeholders), call
  `classify_message` to write per-message origin role (commit `<pending>`).
- Modified
  `packages/llm_tracker_plugin_analytics_sink/tests/test_classifier.py`:
  imported `classify_message`, added 11 new tests covering canonical
  hash collision (sidecar ↔ main flow), wrapper-stripping stability,
  per-message classifier across all five origin shapes (commit `<pending>`).
- Modified
  `packages/llm_tracker_plugin_analytics_sink/tests/test_analytics_sink.py`:
  updated `test_normalization_applied_at_upsert_boundary` for new role
  vocab, added `test_upserts_carry_per_message_origin_roles` and
  `test_upsert_sql_uses_priority_do_update` (commit `<pending>`).

(planned, next steps in order:)

- Write backfill script
  `packages/llm_tracker_plugin_analytics_sink/scripts/backfill_canonical_grouping.py`
  with `--dry-run` (default) and `--apply` flags, single transaction.
- Run backfill `--dry-run` against the live Supabase DB via MCP to
  produce a report; review with operator before `--apply`.
- Apply backfill (operator confirmation required), commit, refresh
  STATUS.md handoff.

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

Live-DB backfill not yet run — pending operator review on dry-run.

## What's left / known limits

- Backfill script + live dry-run + apply (the operator-gated step
  remaining to close out the ADR; everything else is in code).
- The original
  `01KSEVH1XVKBCH6GX1Y00P4WS9` / `01KSEVGY6FT6655DN0J708VPTD` pair
  in production still has the *old* hash and split conversation_id.
  The backfill is what folds them. Until then, *new* sessions get
  the fixed behaviour but historic rows look unchanged.
- `classify_message` does not emit `claude_manage_probe`. The five-
  value vocabulary is reserved for parity with `TurnKind`; the rare
  offline-probe case (list content with `<session>` last text and no
  CC system signature) classifies as `user_input_turn_start` at
  per-message scope because system_text is unavailable. Acceptable
  per the ADR (rare in production; analyst joins
  `plugin_analytics.turn_kind` for the exchange-level distinction
  when needed).

## Handoff

Code checkpoint committed (next: backfill script + dry-run +
operator-reviewed apply). Resume by:

1. Read this worklog's "What's left" section.
2. Open
   `packages/llm_tracker_plugin_analytics_sink/scripts/backfill_canonical_grouping.py`
   (to be created), confirm the dry-run report logic.
3. Run dry-run against the live Supabase DB; show counts to operator
   (hash changes, conversation_id collapses, role changes,
   collision-merge cases).
4. Apply only after operator OK.
5. Commit "backfill: applied ADR-0036 canonical grouping to N rows"
   referencing this worklog.
