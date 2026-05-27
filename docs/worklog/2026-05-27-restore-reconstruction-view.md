# 2026-05-27 · analytics — restore `plugin_analytics_with_messages` view (ADR-0039)

**Author**: Claude Code
**Session trigger**: Operator (verbatim): "원래 supabase view로
plugin_analytics에서 하나의 conversation에서 순차적으로 input과 output을
연결한 결과 (실제로 claude model에 들어가는 결과)를 볼 수 있도록 했었던
거 같은데, 그게 지금 사라진 상태네. 그거 똑같은 기능으로 복구할 수
있음?"
**Related docs**: ADR-0039 (this work), ADR-0038 (dropped the original
view), ADR-0036 (created the original view), prior worklog
`2026-05-26-per-exchange-turn-delta.md` (the drop).

## Interpretation

The view existed under ADR-0036 as `plugin_analytics_with_messages`,
backed by `conversation_messages` row-per-message joined on
`msg_index < n_messages_at_request`. ADR-0038 (commit `121276a`,
2026-05-26) collapsed that schema into per-exchange deltas
(`request_jsonb` + `response_jsonb`) and dropped both the dedup table
and the view, on the assumption that downstream consumers would inline
the reconstruction query from ADR-0038 §"Reconstruction queries".

The operator's question reframes that assumption: inlining the
reconstruction at every inspection site is friction the view existed
to remove. Operator agreed on the restore approach:

1. Same view name (`plugin_analytics_with_messages`).
2. Rebuilt atop the ADR-0038 delta schema (no schema-revert).
3. Main-flow only (`role IN ('user_input', 'tool_result')`) —
   sidecars excluded from `messages_jsonb`, exposed only as the
   underlying row.
4. Added a `system_prompt_resolved` column so consumers don't have to
   re-run the variation-carry-forward subquery.
5. Documented in ADR-0039 + Alembic migration 0021 + live-applied via
   Supabase MCP.

## What was done

- Wrote `docs/decisions/0039-restore-reconstruction-view.md` —
  Accepted ADR, documents the partial reversal of ADR-0038's view
  drop with the new delta-stitching SQL and the rationale for
  excluding sidecars from `messages_jsonb`. (commit `<pending>`)
- Wrote `packages/llm_tracker_server/alembic/versions/0021_restore_messages_view.py` —
  one-shot `CREATE VIEW` on upgrade, `DROP VIEW IF EXISTS` on
  downgrade. Same SQL as ADR-0039 §"Shape". (commit `<pending>`)
- Live-applied via Supabase MCP `apply_migration`
  (`restore_messages_view`): the `CREATE VIEW` + bump of
  `alembic_version` to `0021_restore_messages_view` in one
  transaction. (no commit hash — Supabase-side change)

## Decisions

- **Sidecar `messages_jsonb` is NULL, not its own
  `[{role:'user', content:request_jsonb}]`.** Sidecars are
  out-of-band framework auto-calls. Their full `messages[]` to the
  model on each call is essentially their own `request_jsonb` alone
  (they don't carry conversation history). Leaving `messages_jsonb`
  NULL on these rows makes the "what was in the main conversation
  flow" reading unambiguous; sidecar payloads remain visible via the
  per-row `request_jsonb` column. Documented as Option 2 vs 3 in
  ADR-0039.
- **`(created_at, id)` ordering, not `(created_at)` alone.** ULIDs
  are lexicographically time-sortable so the secondary key
  recovers a deterministic order for the (currently impossible but
  schema-permitted) microsecond tie.
- **Live-apply via Supabase MCP `apply_migration`, not alembic
  `upgrade head`.** Matches the operator-driven flow established
  by ADR-0036 migration 0015 (§"Live apply order" in that
  docstring) and continued through 0019, 0020. The alembic file
  exists for the historical record + future fresh-install path; live
  apply runs through the operator-controlled Supabase channel.

## Verification

Pre-apply dry-run against live data (conv `01KSM87T0P1CW89G7QRCM263P3`,
12 main-flow rows at the time of the query):

```
id                       | role        | n_msgs | first_role | last_role
01KSM87T0P1CW89G7QRCM263P3 | user_input  | 1      | user       | user
01KSM8822K5K2CDRQBYWC7ERXP | tool_result | 3      | user       | user
01KSM88B5FD9XAZ1E5R27M7QBM | tool_result | 5      | user       | user
01KSM88K94QZB0EQZBQ12J4ENS | tool_result | 7      | user       | user
…
01KSM8P28PMK0JEAVBG9XN6MB7 | tool_result | 25     | user       | user
```

Each row's `n_msgs = 2k+1`, every `last_role` is `user`, role
sequence on row 3 reads `["user","assistant","user","assistant","user"]`
— exact A/B/A/B/A alternation as the Anthropic Messages API
specifies for the trailing user turn.

Sidecar handling (conv `01KSKXM2C1CVPMCC6DFN04V2PX`, 9 main-flow + 2
sidecars):

```
id                       | role        | msgs_null | n_msgs | has_sys_resolved
01KSKXM2C1CVPMCC6DFN04V2PX | user_input  | false     | 1      | true
01KSKXNDMKY9Q4WHMPE1E0GTE0 | tool_result | false     | 3      | true
01KSKXQNH8CZMN9N6G2JVDMSPE | user_input  | false     | 5      | true
01KSKXQS326R467W1EYV2XQ8HX | sidecar     | true      | 0      | true
01KSKXTE651CBEJ2WR6WA002KZ | user_input  | false     | 7      | true
…
```

Sidecar rows: `messages_jsonb IS NULL` as designed. The next
main-flow row's `n_msgs` increments by 2 from the prior main-flow
row, not from the sidecar — sidecars don't pollute the count.
`system_prompt_resolved` carries forward correctly: only the first
row has `system_prompt_jsonb IS NOT NULL` (variation-tracking under
ADR-0038), and every subsequent row sees the same resolved value.

Post-apply (live view, same conv):

```
SELECT id, role, jsonb_array_length(messages_jsonb) AS n_msgs,
       (system_prompt_resolved IS NOT NULL) AS has_sys
FROM   public.plugin_analytics_with_messages
WHERE  conversation_id = '01KSM87T0P1CW89G7QRCM263P3'
ORDER  BY created_at;
```

Returns identical shape; `alembic_version.version_num` =
`0021_restore_messages_view`.

Lint + tests:

```
$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker_server/alembic/versions/0021_restore_messages_view.py
All checks passed!

$ .venv/bin/python3.12 -m ruff format --check \
    packages/llm_tracker_server/alembic/versions/0021_restore_messages_view.py
1 file already formatted

$ .venv/bin/python3.12 -m pytest -q
296 passed, 31 skipped in 6.47s
```

Same pass count as the prior commit (`d1e8ae4`) — view-only change,
no Python code touched.

## What's left / known limits

- **Read cost is per-row O(n_main_flow_in_conversation).** Acceptable
  at current scale (largest conversation in the live DB has 41
  main-flow rows; full view scan is sub-second). ADR-0039 §"Open
  questions" flags the threshold (~200 main-flow rows per
  conversation) for a `LATERAL` / windowed-CTE rewrite.
- **No production deploy required.** This is a view; no proxy /
  plugin code path reads or writes through it. Effective immediately
  on the operator-facing SQL surface.
- **No automated test for the view itself.** The verification above
  is empirical against live data. A repo-level test would require
  spinning up a fresh Postgres + seeding `plugin_analytics` rows;
  out of scope for a view-restore change.

## Handoff

ADR-0039 closed. The operator can now query
`plugin_analytics_with_messages` directly and see the full
materialised `messages[]` per exchange plus the carried-forward
system prompt. No outstanding follow-ups on this track.

The prior STATUS "Next single step" (operator deploys to fly to
activate the WebFetch wrapper prefix) remains the outstanding
operator-side item; this restore doesn't depend on or block it.

## Suggestions (untouched)

- None — single-view surgical change.
