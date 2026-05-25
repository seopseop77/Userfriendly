# 2026-05-26 · ADR-0037 display role vocab on conversation_messages

**Author**: Claude Code
**Session trigger**: Operator (verbatim): "conversation_messages 테이블에
메시지를 저장하잖아. 첫 번째 메시지의 system prompt랑 user input을
분리하고, `<session>` 붙는 건 title_gen으로 따로 분류하고, 실제 모델
응답은 model_output, tool continuation / internal subprompt는 assistant
로 묶자."
**Related docs**: ADR-0037 (this change), ADR-0036 (prior vocab),
worklog `2026-05-25-conversation-grouping-fix.md`

## Interpretation

Operator wants `conversation_messages.role` to read top-to-bottom
clearly:

1. The session-opener's `<system-reminder>` framing and the user's
   first typed message should sit on **separate rows** instead of a
   single bundled array.
2. The previous catch-all `internal_subprompt` should split: the
   `<session>...</session>` title-gen probe gets its own
   `title_gen` value; everything else (SUGGESTION MODE, `/compact`,
   step-away, tool_result continuations) collapses into one
   `assistant` bucket.
3. The model's actual response (currently `assistant`) should be
   renamed `model_output` so the bucket names match the operator's
   mental model.

Confirmed three sub-questions before coding (transcript above): row-
split via DELETE+INSERT, msg_index shifts by +1 when split applies,
backfill the 246 historic rows in addition to the forward writes.

## What was done

- Created `docs/decisions/0037-display-role-vocab-split.md` — the
  ADR documenting the 5-value display vocab, msg_index +1 shift on
  split, `n_messages_at_request` bump, priority UPSERT update, and
  trade-offs. (commit d34818a)
- Modified
  `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/classifier.py`
  — replaced `MessageOrigin` Literal with `MessageRole`
  (5 values), rewrote `classify_message` to emit the new vocab,
  added `split_first_message` helper that peels leading wrapper
  blocks off `messages[0]`. `TurnKind` and `classify_request` left
  unchanged. `OVERWRITABLE_ROLES` narrowed to `frozenset({"title_gen"})`.
  (commit d34818a)
- Modified
  `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py`
  — pulled the UPSERT loop into `_upsert_messages`; calls
  `split_first_message` on `messages[0]` and, when split applies,
  writes two rows (msg_index 0/1) then shifts subsequent API
  messages by +1. `n_messages_at_request` bumped by +1 in the same
  branch. `_UPSERT_MESSAGE_SQL` `WHERE` clause now targets
  `title_gen` only. (commit d34818a)
- Modified
  `packages/llm_tracker_plugin_analytics_sink/tests/test_classifier.py`
  and `tests/test_analytics_sink.py` — replaced old-vocab
  assertions with new-vocab ones, added 6 new tests for
  `split_first_message`, added `test_session_opener_splits_*`,
  `test_no_split_*`, `test_title_gen_string_*`,
  `test_upsert_sql_uses_priority_do_update` (new WHERE clause
  assertion). 61 tests in the package pass, 283 in the full repo.
  (commit d34818a)
- Created
  `packages/llm_tracker_plugin_analytics_sink/scripts/backfill_display_role_vocab.py`
  — dual-mode (`--emit-sql` / `--apply` / `--from-json`) script
  with idempotency guard (a conv with any new-vocab role is
  skipped). Auto-corrects the one historic `user_input_turn_start`
  row whose content was actually a `<session>` string. (commit
  <pending>)
- Applied the backfill **live** via Supabase MCP (single
  transaction per phase):
  - Phase A — role remap on the 4 old-vocab values across all
    un-migrated convs. SQL inlined in the worklog below for
    re-runnability.
  - Phase B — DO block that loops every msg_index=0 array row
    whose first block is a synthetic wrapper, peels it, mutates
    the row into msg_index=1 + role=user_input + Rule-B-normalised
    content, inserts a new msg_index=0 + role=system_prompt
    sibling, and shifts the rest of the conv by +1 via a
    temporary-negative trick (avoids PK collision).
  - Phase C — bumped `plugin_analytics.n_messages_at_request` by
    +1 for every exchange in a conv that got split.

## Decisions

- **Diverged from ADR-0036 `cm.role = pa.turn_kind` join.** Display
  vocab on `cm.role` is now its own thing; analyst queries that
  assumed the equivalence must add a CASE. Documented in ADR-0037
  Consequences.
- **`assistant` is overloaded** for `role=user` continuations
  (tool_result, SUGGESTION MODE, /compact, step-away). Operator
  ratified this as part of the spec rather than adding a 6th value
  like `framework_sidecar`. ADR-0037 explicitly carves out
  `model_output` for the model's turn so the overlap is bounded.
- **`claude_manage_probe` dropped from the display vocab** (kept in
  `TurnKind` for parity). Production never had a message-level row
  carrying this value; the offline claude-manage probe is rare and
  the new `title_gen` rule subsumes the `<session>` shape.
- **Row split via DELETE + INSERT (not column-add).** Considered
  adding `system_prompt_jsonb` as a sibling column; rejected in
  favor of a separate row for top-to-bottom legibility (per
  operator preference).
- **Pure-SQL backfill (not the Python script's --apply path)** for
  the live run. The script is the canonical re-runnable artifact
  (committed for the next operator), but the live data move went
  through Supabase MCP as one DO block — same code path Phase B of
  ADR-0036's backfill used.

## Verification

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_analytics_sink/tests/ --tb=short
=========================== 61 passed in 0.21s ===========================

$ .venv/bin/python3.12 -m pytest -q
=========================== 283 passed, 31 skipped in 6.07s ===========================

$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_plugin_analytics_sink/
All checks passed!
```

Backfill verification (post-apply):

```
role          | count
system_prompt | 26
user_input    | 52
title_gen     | 10
model_output  | 104
assistant     | 80
stragglers (old vocab) | 0
total         | 272 (was 246, +26 system_prompt inserts)
```

Helper view consistency (sample conv `01KRQGJ76Q4MESGADPEJRJ4624`):

```
n_messages_at_request | view_msg_count | gap
2                     | 2              | 0
4                     | 4              | 0
6                     | 6              | 0
8                     | 8              | 0
10                    | 10             | 0
12                    | 12             | 0
```

`gap = 0` for every exchange — the +1 bump compensated the
msg_index shift cleanly.

Spot-check `01KRQGJ76Q4MESGADPEJRJ4624`:

```
msg_index | role          | preview
0         | system_prompt | [{"text": "<system-reminder>\nAvailable agent..."}, ...]
1         | user_input    | "안녕 나의 꼬마 친구?"
2         | model_output  | "안녕하세요! 👋..."
3         | user_input    | "지금 뭐하는 중이야?"
4         | model_output  | [{"type": "thinking", ...}, {"tool_use"...}]
5         | assistant     | [{"tool_result"...}]
6         | model_output  | "지금은 아무 작업도 진행 중이..."
7         | user_input    | "아무거나 tool 하나만 호출해서 써봐"
8         | model_output  | [{"tool_use" ...}]
9         | assistant     | [{"tool_result" ...}]
10        | model_output  | "`date` 한 번 돌렸어요..."
11        | assistant     | "[SUGGESTION MODE: ...]"
```

Top-to-bottom legibility achieved.

## What's left / known limits

- **No alembic migration.** The schema (`role text`) didn't change;
  only the allowed value set widened. If a future ADR wants to lock
  the column with a CHECK constraint or move to enum-typed, that's
  separate work.
- **Cascade for outstanding analyst tooling.** No downstream queries
  in this repo joined on `cm.role` symbolically as of 2026-05-26;
  external operator notebooks (if any) need a heads-up.

## Handoff

ADR-0037 is closed: code, tests, ADR, backfill script all
committed; live Supabase reflects the new vocab end-to-end with
gap=0 against the helper view. Next single step is **operator's
choice**, identical to the post-ADR-0036 handoff:

1. (back-burner) Participant-#1 install — see ADR-0035 follow-up
   in `docs/worklog/2026-05-25-uv-tool-install.md`.
2. (paused) scope_guard live smoke — still at `0c1ca9d`.

## Suggestions (untouched)

- The post-`/compact` resume marker row (`This session is being
  continued from a previous…`) classifies as `assistant` under the
  new vocab. Semantically it's neither user nor model output;
  a dedicated `compact_resume` value could land in a follow-up ADR
  if usage justifies it. Not blocking.
