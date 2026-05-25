# ADR-0036 · Canonical conversation grouping, per-message origin role, priority UPSERT

- **Status**: Accepted
- **Date**: 2026-05-25
- **Author**: Claude Code (operator-directed)
- **Related**:
  - Worklog: `docs/worklog/2026-05-25-conversation-grouping-fix.md`
  - Supersedes parts of: ADR-0032 (Candidate 1 UPSERT-DO-NOTHING policy),
    the (B) rule documented in `2026-05-19-turn-classification.md`
  - Touches `plugin_analytics` semantics and the `conversation_messages`
    schema — both listed under CLAUDE.md §9 public interfaces.

## Context

Three defects surfaced together when an operator inspected
conversation `01KSEVH1XVKBCH6GX1Y00P4WS9` (2026-05-25 06:00–06:03 UTC):

1. **Split conversation_id on session start.** A `<session>` Claude
   Code sidecar (turn_kind=`internal_subprompt`) and the immediately
   following main-flow user turn carry the same human-typed text
   ("너무 반가워! 잘 지냈어?") but produce different `first_msg_hash`
   values, so they live under different `conversation_id`s. The hash
   is computed over the concatenated text of `messages[0]`: the
   sidecar's payload is `"<session>...</session>"` (string content);
   the main flow's payload is `[<system-reminder>..., <user text>]`
   (list content). Neither encoding reflects the *user's typed text*,
   so semantically identical session starts hash apart.

2. **Silent loss of real user input when a sidecar collides with a
   later main turn.** `conversation_messages` UPSERTs with
   `ON CONFLICT (conversation_id, msg_index) DO NOTHING`. A
   `[SUGGESTION MODE: ...]` sidecar that fires after assistant turn N
   writes to msg_index (N+1) before the user's next typed message
   arrives at the *same* msg_index. The user message is then dropped
   silently. Reproduced live: msg_index 4 of conv
   `01KSEVH1XVKBCH6GX1Y00P4WS9` shows the SUGGESTION prompt instead of
   the operator's "현재 mcp 리스트 알려줘" question; the assistant's
   Bash `claude mcp list` call (msg 5) and its result (msg 6) survived
   because they landed at fresh indexes.

3. **`role` field is API-protocol-truthy but analytics-misleading.**
   The Anthropic Messages API uses `role=user` both for typed input
   and for synthetic continuations (`tool_result`, SUGGESTION MODE,
   title-gen probe). The stored `conversation_messages.role` carries
   the API role verbatim, so a downstream consumer cannot tell typed
   input apart from Claude Code's auto-injected sub-prompts without
   joining `plugin_analytics.turn_kind`. There is no `exchange_id` or
   `source_kind` column on `conversation_messages` to recover from.

Defect 1 is a hashing-policy issue; defects 2 and 3 share root cause
(sidecars and real turns sharing the same key space with no priority
distinction). Folding them into one ADR avoids two coupled half-fixes.

## Options considered

1. **Status quo + manual repair only.** Backfill the affected rows by
   hand; keep code unchanged. Lets the defects recur on every new
   sidecar collision. Rejected.

2. **(E) Canonical user-text hash; (P) priority UPSERT; (V) reuse
   turn_kind vocab for role.** Three coordinated changes:
   - Hash `first_msg_hash` over the *user-typed text* extracted from
     `messages[0]`, not the wrapped concatenation. Both the
     `<session>` sidecar string ("너무 반가워!") and the main flow's
     last non-wrapper text block ("너무 반가워!") collapse to the
     same canonical string; the (B) chain-lookup rule then inherits
     the same `conversation_id`.
   - Replace `ON CONFLICT DO NOTHING` with `DO UPDATE` gated on a
     priority rule: a stored `internal_subprompt` row can be
     overwritten by an arriving `user_input_turn_start`,
     `tool_continuation`, or `assistant`; non-`internal_subprompt`
     rows are preserved (idempotency under stream retries still
     holds for real content).
   - Move `conversation_messages.role` from API protocol values
     (`user`/`assistant`) to the per-message origin vocabulary
     (`user_input_turn_start`, `tool_continuation`,
     `internal_subprompt`, `claude_manage_probe`, `assistant`).
     Reuses the existing `turn_kind` vocabulary plus one new
     `assistant` value so `cm.role = pa.turn_kind` joins are natural.

3. **Drop sidecars from `conversation_messages` entirely.** Skip the
   UPSERT when `turn_kind in (internal_subprompt, claude_manage_probe)`.
   Eliminates collisions structurally. Loses visibility of sidecar
   content from the dedup table (operator must read
   `plugin_analytics.response_json` to debug a sidecar). Rejected as
   the primary fix but kept as a fallback if (P) proves too subtle.

4. **Add `exchange_id` / `source_kind` column; keep `role` as API
   protocol.** Adds a column instead of overloading `role`. Cleaner
   schema in isolation but doubles the analyst's mental model
   (`role` plus a parallel column to interpret). Rejected per
   operator preference for a single richer `role`.

## Decision

**Pick option 2 (E + P + V).** Three coordinated changes shipped
together in one migration + plugin patch + backfill:

1. **(E) Canonical user-text hash.** `first_msg_hash` is the
   SHA-256[:16] of the user-typed canonical text extracted from
   `messages[0]`:
   - String content: strip a leading `<session>...</session>`
     wrapper, hash the inner text; otherwise hash the string.
   - List content: walk blocks in reverse, skip blocks whose text
     starts with any synthetic-wrapper prefix (the same
     `_SYNTHETIC_WRAPPER_PREFIXES` set the classifier uses for
     rule 6); hash the first remaining text block.
   - No real user text (only wrappers, or empty): canonical is the
     empty string. Distinct sessions with zero typed input collapse;
     acceptable per the existing (B) trade-off.

2. **(P) Priority UPSERT.** `conversation_messages` writes change
   from `ON CONFLICT DO NOTHING` to:
   ```sql
   ON CONFLICT (conversation_id, msg_index) DO UPDATE
   SET role = EXCLUDED.role,
       content_jsonb = EXCLUDED.content_jsonb
   WHERE conversation_messages.role = 'internal_subprompt'
     AND EXCLUDED.role IN (
       'user_input_turn_start', 'tool_continuation', 'assistant'
     )
   ```
   Sidecar-first arrivals no longer block real content; real-first
   arrivals are not overwritten by later sidecars (the `WHERE`
   guards both directions). Stream-retry idempotency for real
   content is preserved because `EXCLUDED.role` of a retry equals
   the stored role, so the `WHERE` filter elides the UPDATE.

3. **(V) Per-message origin vocab on `role`.** Five values:
   - `user_input_turn_start` — actual user-typed input (real
     non-wrapper text block found)
   - `tool_continuation` — message carries a `tool_result` block
   - `internal_subprompt` — string content, or list with only
     synthetic-wrapper text blocks (SUGGESTION MODE, `/compact`
     summarize, step-away recap, title-gen sidecar)
   - `claude_manage_probe` — `<session>` wrap on list content with
     no Claude Code system signature (rare; dead in production)
   - `assistant` — `role=assistant` messages

   The classifier exposes a new `classify_message(msg) -> str`
   helper; the plugin calls it inside the UPSERT loop in place of
   the raw API `role`. The five values are a superset of
   `turn_kind` (the original four request-level kinds plus
   `assistant`), so `cm.role = pa.turn_kind` joins line up.

The backfill is a Python script under
`packages/llm_tracker_plugin_analytics_sink/scripts/` that:
1. Rehashes every `plugin_analytics` row's `first_msg_hash` from
   the joined `conversation_messages.content_jsonb` of its
   `messages[0]` (the helper view exposes the array shape).
2. Re-runs the (B) chain-lookup with the new hashes to assign
   `conversation_id` from scratch, ordered by `created_at`.
3. Reclassifies every `conversation_messages` row via
   `classify_message` and writes the new `role` value.
4. Reports collision counts and orphan rows before any write; runs
   in a single transaction with `--apply` to commit.

## Consequences

- **Resolves defect 1.** `<session>` sidecars and the matching main
  flow share a `conversation_id` post-fix and post-backfill.
- **Resolves defect 2.** Real user input is no longer silently
  displaced by sidecars; the priority UPSERT rule lets later real
  content overwrite a sidecar placeholder.
- **Resolves defect 3.** `conversation_messages.role` now tells a
  reader the per-message origin without joining `plugin_analytics`.
- **Schema migration required** (alembic 0019) — no DDL change to
  `conversation_messages` itself (the column stays `text`), but the
  set of valid values widens. Existing downstream queries that
  filter `role IN ('user','assistant')` need updating; an audit
  pass on `packages/` and analytics docs is part of the rollout.
- **Hash semantics change is irreversible without source data.**
  Plugin rows lose their original `messages_json` (dropped by
  migration 0016) so the backfill recomputes hashes from
  `conversation_messages.content_jsonb` via the helper view. Rows
  whose `messages[0]` is now `internal_subprompt`-shaped only
  (sidecar wrote there first, real turn never landed) keep that
  shape — the backfill cannot resurrect the lost user input. The
  rebuild report enumerates these rows so the operator can decide
  whether to leave them as-is or annotate.
- **(B) rule still applies** on the new hash. Two genuinely-separate
  sessions whose user-typed first message is byte-identical
  ("hi", "안녕") still fold into one conversation per org, as
  ADR-0032 / B-rule trade-off. Org isolation is preserved via the
  `org_id` filter in `_PREV_BY_HASH_SQL`.
- **`internal_subprompt` rows that arrive *first* and are never
  overwritten by a real turn remain in `conversation_messages`.**
  Useful for sidecar debugging; an analyst filters them out with
  `WHERE role NOT IN ('internal_subprompt', 'claude_manage_probe')`.
- **Reversible via downgrade migration + reverse backfill** until
  any new column dependency lands.

## Open questions

- The backfill report may surface cases where two distinct user
  sessions previously sharing the same `<session>` text (e.g. two
  operators both typing "안녕") were stored as two
  `conversation_id`s and will, post-rebuild, fold into one. We will
  inspect the report before applying; if collapse rate is non-trivial,
  consider widening the hash with a low-cardinality discriminator
  (e.g. `cwd`) in a follow-up ADR. Not blocking the initial fix.
