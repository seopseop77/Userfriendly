# ADR-0041 · Scope conversation grouping by client session id

- **Status**: Accepted
- **Date**: 2026-05-30
- **Author**: Claude Code (operator-directed)
- **Related**:
  - Amends the (B) chain-lookup rule of ADR-0036 (canonical
    conversation grouping), carried forward by ADR-0038 and ADR-0040.
  - Builds on the `session_id` capture added 2026-05-30 (commit
    907f95f, migration 0022) — see
    `docs/worklog/2026-05-30-session-id-extraction.md`.
  - Evidence: live wire capture (CC 2.1.158) + operator verification;
    campaign rounds r020 (cross-UUID unification) and A-1
    (`01KSJC53…` cross-session sidecar pollution) in
    `docs/experiments/headless-subsession/results/2026-05-28-campaign-summary.md`.
  - Touches `plugin_analytics` conversation grouping — a CLAUDE.md §9
    public interface.

## Context

ADR-0036's (B) rule groups exchanges by `first_msg_hash` within an
`org_id`: the chain-lookup inherits the most recent same-hash row's
`conversation_id`. When ADR-0036 was written the proxy had **no access
to a client conversation identity**, so the first-message hash was the
only signal stable across HTTP calls. A documented consequence: two
genuinely distinct sessions whose first real user message is
byte-identical collapse into one `conversation_id` (campaign r020,
"working as designed"; A-1 showed it accumulating cross-session sidecar
pollution in `01KSJC5354RT1XSGBFPZBQT4BB`). ADR-0040 explicitly left
this identical-opener collision to a future ADR.

Two facts established 2026-05-30 change what is possible:

1. **The client session id is on the wire.** Claude Code sends it in
   the request body `metadata.user_id` (a JSON string
   `{"device_id", "account_uuid", "session_id"}`) and in an
   `x-claude-code-session-id` header. The sink now captures it into
   `plugin_analytics.session_id` (migration 0022).
2. **`session_id` is the client's conversation identity, with one
   wrinkle.** Operator-verified via real sessions:
   - A sub-agent (Agent tool) shares its **parent's** `session_id`,
     but has a **different** first real message.
   - `--resume` of a conversation (even after exit, in a new window)
     **preserves** the original `session_id`.

So within one logical conversation `(session_id, first_msg_hash)` is
stable across turns and resumes; a sub-agent differs only in
`first_msg_hash`; two coincidentally-identical openers differ only in
`session_id`.

## Options considered

1. **Status quo — `first_msg_hash` only.** Coincidental identical
   openers keep merging; no parent↔sub-agent link is usable for
   grouping. Rejected — the collision is now fixable.

2. **Group by `session_id` alone (one session = one conversation).**
   Simple, but **collapses every sub-agent into the parent
   conversation** (sub-agents share `session_id`), destroying the
   per-agent separation the hash gives today. Also can't separate two
   distinct logical conversations that reuse a session id across a
   `/clear` or `/compact` (where the opener changes but the session id
   may not). Rejected.

3. **Composite key — scope the (B) chain-lookup by `session_id`.**
   Add `session_id` to the chain-lookup predicate so a row inherits a
   prior `conversation_id` only when **both** `first_msg_hash` **and**
   `session_id` match. `session_id` links the session family
   (parent + sub-agents + resumes); `first_msg_hash` separates members
   within it (each sub-agent, each post-`/clear` or post-`/compact`
   opener). NULL `session_id` (non-Claude-Code clients, older
   versions, missing metadata) matches NULL via `IS NOT DISTINCT FROM`,
   preserving exactly the ADR-0036 hash-only behavior for that traffic.
   Chosen.

## Decision

**Pick option 3.** Change `AnalyticsSink._resolve_conversation` /
`_PREV_BY_HASH_SQL` in `plugin.py` only:

- The chain-lookup gains `AND session_id IS NOT DISTINCT FROM
  :session_id`. `_resolve_conversation` receives the row's
  `session_id` and binds it.
- `IS NOT DISTINCT FROM` makes `NULL = NULL` match, so traffic without
  a captured session id (other clients, historic rows) groups by
  `first_msg_hash` alone — the unchanged ADR-0036 fallback. No regress.
- Everything else is untouched: the (E) hash computation (incl.
  ADR-0040's wrapper scan), the `turn_seq` axis, the (V) role vocab,
  the system-variation tracker.

**No migration.** The `session_id` column already exists (0022). The
existing `idx_plugin_analytics_first_msg_hash` index
(`(first_msg_hash, created_at DESC)`) still serves the query —
`session_id` is a cheap equality filter over the small per-hash,
per-session row set. Revisit the index only if rows-per-hash grows
large (cf. ADR-0039's scale note).

## Consequences

- **Resolves the identical-opener collision** ADR-0040 deferred. Two
  sessions that both open with "반가워" now stay separate (distinct
  `session_id`). The A-1 cross-session pollution mechanism is closed
  for any traffic carrying a session id.
- **Parent and sub-agents stay separate conversations** (distinct
  `first_msg_hash`) yet are now **linkable** by the shared `session_id`
  column — enabling session-level rollups (cost/drift across the whole
  agent tree) as a later query concern, without a grouping change.
- **Resume still groups correctly** — same `session_id` + same
  `first_msg_hash` across turns and across windows.
- **Reverses ADR-0036's cross-UUID unification** for session-bearing
  traffic. Intentional: that unification was a byproduct of the session
  id being unavailable, not a desired feature. Traffic *without* a
  session id retains the old behavior.
- **Forward-only; no backfill.** Historic rows keep their old
  `conversation_id` and have `session_id = NULL`; a new session-bearing
  request will not chain onto a NULL-session historic row, giving a
  clean cutover (same irreversibility ADR-0036/0040 noted — the full
  message array is not retained).
- **Reversible** — pure plugin logic; revert by dropping the
  `session_id` predicate. No schema dependency added by this ADR.

## Open questions

- Same first real message *within one session* across two sub-agents
  would still merge — negligible (a sub-agent's opener is its task
  prompt) and no worse than today.
- Whether to surface `session_id` in `plugin_analytics_with_messages`
  and build the session-level rollup queries is left to a follow-up
  (the column is on the base table today).
