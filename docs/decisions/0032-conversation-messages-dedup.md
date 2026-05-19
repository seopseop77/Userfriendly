# ADR-0032 · Dedup `plugin_analytics` message bodies into `conversation_messages`

- **Status**: Accepted
- **Date**: 2026-05-19
- **Author**: Claude Code (operator-directed)
- **Related**:
  - Handoff doc: `docs/worklog/2026-05-19-candidate-1-handoff.md`
  - Prior data-side track: `docs/worklog/2026-05-19-scrubber-json-aware-and-b-rule.md`
  - Touches the `plugin_analytics` schema, listed under CLAUDE.md §9 public
    interfaces.

## Context

`plugin_analytics.messages_json` stores the full Anthropic Messages API
request body for every exchange. Because Claude Code re-sends the entire
message history on each turn (tool-result continuations and the next
user-typed turn alike), a 9-step chain duplicates `messages[0]`
9 times, `messages[1]` 8 times, and so on — quadratic growth on
conversation length. The 2026-05-19 STRESS-1 ~ STRESS-6 single-session
stress run (main conv `01KS084X32YARSRKGBY35ACRYM`) measured a **4.8×
duplication factor** on a 23-message conversation; the factor climbs
linearly with conversation length.

A normalization-whitelist study against the same data identified that
only two fields break byte-level prefix identity across same-conversation
rows after stripping `cache_control`:

1. **Rule A** — `cache_control` markers on content blocks shift as
   prompt-caching breakpoints move between rows.
2. **Rule B** — Anthropic SDK / Claude Code serialises a user message
   `[{"type":"text","text":"X"}]` on the first send, then re-sends the
   same message as bare string `"X"` on every subsequent turn.

With those two rules applied, `tool_use.id`, `tool_result.tool_use_id`,
and extended-thinking `signature` were all verified **stable** across
same-message rows — no normalization needed for them.

## Options considered

1. **Candidate 1 — row-per-message dedup table, keyed by
   `(conversation_id, msg_index)`.** UPSERT-by-key on every write;
   `plugin_analytics` keeps a pointer `n_messages_at_request`.
   - Pros: idempotent under streaming retries (a same-key re-write
     silently keeps the first arrival); recovery is a pure
     content-equality check; reconstruction = simple ORDER BY.
   - Cons: requires one normalization spec the plugin and the
     backfill both have to honour exactly.

2. **Candidate 2 — row-level delta with `parent_id` pointer.** Each row
   stores only the *new* messages plus a chain pointer to the previous
   row in the same conversation.
   - Pros: zero re-write of unchanged messages by construction.
   - Cons: chain walk is brittle — a single missing or duplicated row
     poisons every descendant; stream retries that land the *same*
     new turn twice would either double-insert or break the chain.
     Recovery requires reconstructing the chain, not just diffing.

## Decision

**Pick Candidate 1.** Two reasons drive the choice:

1. **Idempotency wins.** `INSERT ... ON CONFLICT
   (conversation_id, msg_index) DO NOTHING` is naturally safe against
   stream retries, duplicate webhooks, and the failure-recovery paths
   the plugin already exercises. Candidate 2's chain walk is unsafe
   against the same conditions.
2. **Normalization is already nailed.** The STRESS-1 ~ STRESS-6 study
   produced a 2-rule canonicalisation (`canonical_message`) that turns
   same-content messages into byte-equal JSON. No discovery work
   remains; the spec is in the handoff doc §3.

The trade-off Candidate 1 forecloses — slightly more index/UPSERT cost
per write — is acceptable: writes are not the hot path (analytics is
write-once per exchange, never queried client-side), and the dedup
savings ratio compounds with conversation length.

## Consequences

- `plugin_analytics.messages_json` is **dropped** in the same migration
  that introduces `conversation_messages`. Operator confirmed this is
  intentional ("후보 1 구현할 때 drop하는 걸로 하고"). No known
  external consumer reads the column today.
- A helper view `plugin_analytics_with_messages` reconstructs the
  original row shape for any consumer that wanted the joined form.
- The plugin write path runs the per-message UPSERTs inside the same
  transaction as the analytics-row INSERT, so the row never references
  messages that aren't yet visible.
- Normalization is centralised in a single Python function
  (`canonical_message`) reused by both the plugin and the backfill
  script — there is no second implementation that could drift.
- Per the §5 V5 verification, the STRESS conv yields ~5× storage
  savings; longer chains save more (≥9× at 17 messages, ≥16× at 30).

## Open questions

None outstanding. The handoff doc §8 R3 mitigation chose the Python
script form for the backfill specifically to avoid two divergent
implementations of the normalization rule; the SQL form remains a
documented fallback only.
