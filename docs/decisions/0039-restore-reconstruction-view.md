# ADR-0039 · Restore `plugin_analytics_with_messages` view atop the per-exchange delta schema

- **Status**: Accepted
- **Date**: 2026-05-27
- **Author**: Claude Code (operator-directed)
- **Related**:
  - Worklog: `docs/worklog/2026-05-27-restore-reconstruction-view.md`
  - **Partially reverses** ADR-0038's "DROP VIEW plugin_analytics_with_messages"
    decision — but rebuilds the view atop the new per-exchange delta
    schema rather than the retired `conversation_messages` table.
  - Touches public interfaces per CLAUDE.md §9: re-introduces the
    `plugin_analytics_with_messages` view name with a redefined source
    (delta stitching) and one added column (`system_prompt_resolved`).

## Context

ADR-0036 created `plugin_analytics_with_messages` as a convenience view
that materialised the `messages[]` array visible to any past exchange,
by joining `plugin_analytics` with the per-message `conversation_messages`
dedup table on `msg_index < n_messages_at_request`.

ADR-0038 (commit `121276a`, 2026-05-26) collapsed the per-message table
into a per-exchange delta on `plugin_analytics` (`request_jsonb` +
`response_jsonb` + `role` + `system_prompt_jsonb`) and dropped both the
`conversation_messages` table and the view. The reconstruction SQL was
preserved as a documented query pattern in ADR-0038 §"Reconstruction
queries", on the assumption that downstream consumers would inline it
as needed.

Operator feedback 2026-05-27: "the view that let me see, for one
conversation, the sequential input/output (what actually goes into the
Claude model) — that's gone now. Can you restore the same
functionality?" The reconstruction query is non-trivial (a 3-arm UNION
ALL with a window-style alternation and a correlated subquery for
`system_prompt_resolved`) and inlining it at call sites is friction
the original view existed precisely to remove. The "documented as a
query pattern" route under-served the actual day-to-day inspection
workflow.

## Options considered

1. **Leave it dropped, point at ADR-0038 §"Reconstruction queries".**
   Status quo. Rejected — the SQL is too long to retype each time;
   inspection from a SQL client is the primary use case and the view
   existed to remove this exact friction.

2. **Restore the view, main-flow only, with `system_prompt_resolved`
   (chosen).** Rebuild atop `request_jsonb` + `response_jsonb` per
   ADR-0038 §"Reconstruction queries". Sidecars exposed as plain rows
   only — their `messages_jsonb` is NULL, since sidecars are
   out-of-band framework calls whose `messages[]` is just their own
   `request_jsonb` and including them in the alternation would
   confuse the "what the main thread looked like" reading.

3. **Restore the view, all rows including sidecars in the
   alternation.** Sidecars would interleave into `messages_jsonb`,
   matching the literal sequence the model saw on each request. Rejected
   per operator preference — sidecars are framework noise and the
   primary use case is reviewing the user-perceived conversation flow.

4. **Materialised view + REFRESH trigger.** Faster reads, but adds
   refresh staleness and trigger surface for ≈ 89 rows total — bad
   trade. Rejected on volume.

## Decision

**Pick option 2.** Restore `plugin_analytics_with_messages` as a regular
(non-materialised) view atop the ADR-0038 schema, main-flow only.

### Shape

```sql
CREATE VIEW plugin_analytics_with_messages AS
SELECT
    pa.*,

    -- Reconstruction of the messages[] array visible to this exchange.
    -- For main-flow rows: alternating user/assistant pairs from prior
    -- main-flow exchanges in this conversation, with the current row's
    -- request appended as the trailing user message. Sidecars
    -- contribute nothing.
    -- For sidecar rows: NULL (they are out-of-band; their own
    -- request_jsonb is the entire payload and is already visible on
    -- the row).
    CASE
        WHEN pa.role IN ('user_input', 'tool_result') THEN (
            SELECT jsonb_agg(msg ORDER BY ord, kind, id_tiebreak)
            FROM (
                SELECT
                    jsonb_build_object('role', 'user',
                                       'content', prior.request_jsonb) AS msg,
                    prior.created_at AS ord,
                    0 AS kind,
                    prior.id AS id_tiebreak
                FROM plugin_analytics prior
                WHERE prior.conversation_id = pa.conversation_id
                  AND prior.role IN ('user_input', 'tool_result')
                  AND prior.created_at < pa.created_at

                UNION ALL

                SELECT
                    jsonb_build_object('role', 'assistant',
                                       'content', prior.response_jsonb -> 'content') AS msg,
                    prior.created_at AS ord,
                    1 AS kind,
                    prior.id AS id_tiebreak
                FROM plugin_analytics prior
                WHERE prior.conversation_id = pa.conversation_id
                  AND prior.role IN ('user_input', 'tool_result')
                  AND prior.created_at < pa.created_at

                UNION ALL

                SELECT
                    jsonb_build_object('role', 'user',
                                       'content', pa.request_jsonb) AS msg,
                    pa.created_at AS ord,
                    0 AS kind,
                    pa.id AS id_tiebreak
            ) m
        )
        ELSE NULL
    END AS messages_jsonb,

    -- The system text in effect at this exchange. ADR-0038's
    -- variation-tracking stores system only when it changes, so naive
    -- `pa.system_prompt_jsonb` reads NULL on most rows. This column
    -- carries forward the most recent non-null entry up to and
    -- including this row, so consumers don't repeat the lookup.
    (
        SELECT s.system_prompt_jsonb
        FROM plugin_analytics s
        WHERE s.conversation_id = pa.conversation_id
          AND s.created_at <= pa.created_at
          AND s.system_prompt_jsonb IS NOT NULL
        ORDER BY s.created_at DESC
        LIMIT 1
    ) AS system_prompt_resolved
FROM plugin_analytics pa;
```

### Differences from the ADR-0036 / ADR-0037 view

| field | ADR-0036/0037 view | ADR-0039 view |
|---|---|---|
| `messages_jsonb` shape | `[{role, content}, ...]` from `conversation_messages` rows | `[{role, content}, ...]` synthesised from `request_jsonb` + `response_jsonb` of prior main-flow rows |
| `messages_jsonb` for sidecar | included (separate `sidecar`/`title_gen` rows interleaved) | **NULL** (main-flow only) |
| `system_prompt_resolved` | not present | **new column** (carries forward variation-tracked system) |
| storage cost | row-per-message dedup table | zero new storage (view only) |
| read cost | join on `(conv_id, msg_index)` | correlated subquery scanning rows in same `conversation_id` (window-style) |

### Tiebreaker — why `id` after `created_at`

`created_at` is `timestamp with time zone` (microsecond precision). Two
exchanges within the same conversation at the same microsecond are
theoretically possible (parallel sub-agents are not currently a thing
in Claude Code, but the schema allows it). ULIDs are
lexicographically sortable by their internal timestamp; using `id`
as the secondary sort recovers a deterministic ordering even in the
ties.

## Consequences

- **Restores the inspection workflow.** A SQL client query against
  `plugin_analytics_with_messages` returns one row per exchange with
  the full materialised messages array — same legibility as before.
- **Carries forward `system`.** The `system_prompt_resolved` column
  removes the second-query burden that ADR-0038's variation-tracking
  schema introduced for any consumer asking "what was the system text
  on row R."
- **Sidecars are visible as rows but absent from `messages_jsonb`.**
  Querying sidecars themselves: `WHERE role = 'sidecar'` — the
  per-row `request_jsonb` carries the synthetic message.
- **Read cost is per-row O(n_main_flow_in_conversation).** Acceptable
  at current scale (largest conversation ≈ 41 rows). If a future
  conversation grows past a few hundred main-flow rows, the
  correlated subquery becomes the slowest part of any
  full-table view scan — at that point convert to a windowed CTE
  with a single pass.
- **Reversibility**: trivial. The view is a one-line `DROP`; no data
  depends on it.
- **No ADR-0038 contract is broken.** ADR-0038 explicitly preserved
  the reconstruction as a documented query pattern; this ADR just
  packages that pattern into a view.

## Open questions

- **Window-CTE rewrite threshold.** When does the per-row correlated
  subquery become slow enough to motivate a `LATERAL` / windowed
  rewrite? Revisit when any single conversation crosses ≈ 200
  main-flow rows or when a full view scan takes more than 1s on the
  fly Postgres tier.
- **Should `system_prompt_resolved` exist when the row itself has a
  non-null `system_prompt_jsonb`?** Today: yes — the carry-forward
  query naturally returns `pa.system_prompt_jsonb` when the most
  recent non-null up to and including `pa` IS `pa.system_prompt_jsonb`.
  Consumers can always read the raw column instead; no harm in
  duplicating.
