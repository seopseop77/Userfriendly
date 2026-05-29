# ADR-0040 · Scan past wrapper-only messages for the conversation-grouping hash

- **Status**: Accepted
- **Date**: 2026-05-30
- **Author**: Claude Code (operator-directed)
- **Related**:
  - Amends the (E) canonical-user-text hash rule of ADR-0036
    (canonical conversation grouping), carried forward unchanged by
    ADR-0038 (per-exchange turn delta).
  - Evidence: `docs/experiments/headless-subsession/results/2026-05-29-s001-interactive-slash.md`
  - Finding: `docs/worklog/2026-05-28-headless-subsession-probe.md`
    Suggestion #8.
  - Touches `plugin_analytics` conversation grouping — a CLAUDE.md §9
    public interface.

## Context

ADR-0036 (E) computes `first_msg_hash` as the SHA-256[:16] of the
*canonical user-typed text* of **`messages[0]` only**. When every text
block of `messages[0]` is a synthetic wrapper, `_canonical_user_text`
returns the empty string, so the row's hash is `SHA-256("")` =
`e3b0c44298fc1c14`. ADR-0036 accepted this ("distinct sessions with
zero typed input collapse; acceptable per the existing (B) trade-off").

That trade-off turns out to be triggered by an ordinary action. The
post-`/compact` **resume marker** (`"This session is being continued…"`)
is a registered `_SYNTHETIC_WRAPPER_PREFIXES` entry. After a real
`/compact`, Claude Code rewrites history so `messages[0]` becomes the
resume-marker block — wrapper-only — and stays there for every
subsequent turn. So `_canonical_user_text(messages[0])` is empty and
**every post-compact turn hashes to `SHA-256("")`**. The (B)
chain-lookup then absorbs them into the single global empty-text
conversation bucket, mixed with unrelated sidecars from other
sessions/days.

Live evidence (2026-05-29 interactive slash probe, org-local):
conversation `01KSJC5354RT1XSGBFPZBQT4BB` accumulated WebSearch/WebFetch
sidecars (2026-05-26 → 05-28), then the `s001` post-compact turn
`"resumed"`, then a separate session's post-compact turns
`"강아지 좋아해?" / "강아지 vs 고양이" / "넌 뭐가 더 좋아"` — all with
`first_msg_hash = e3b0c44298fc1c14`, all `role=user_input`, sharing a
meaningless global `turn_seq` counter. A genuinely new conversation's
turns are scattered into a foreign bucket rather than grouped.

This is reproducible through normal interactive `/compact`, so the
"rare/contrived" premise that closed Suggestion #4 no longer holds.

## Options considered

1. **Status quo.** Empty canonical collapses; every post-compact turn
   orphans into the global empty-text bucket. Rejected — corrupts
   conversation reconstruction for any compacted session.

2. **Drop `"This session is being continued"` from
   `_SYNTHETIC_WRAPPER_PREFIXES`.** Then `messages[0]`'s canonical
   becomes the marker text → a session-distinct, stable key. But that
   tuple is shared with `classify_message` (role) and
   `extract_request_content` (`request_jsonb` stripping): a marker-only
   message would reclassify from `sidecar` to `user_input`, and the
   marker prose would leak into stored bodies. It also assumes the
   marker always sits at `messages[0]`, which is unverified (the marker
   is never persisted, so it cannot be inspected from the sink). Rejected
   — couples three concerns that want different answers, with regression
   risk.

3. **Scan forward to the first real user message.** Compute
   `first_msg_hash` from the canonical text of the **first `role=user`
   message that carries real (non-wrapper) text**, scanning past
   leading wrapper-only user messages (the resume marker) and skipping
   non-user messages. When no user message carries real text,
   `first_msg_hash = None` and the row opens its own `conversation_id`
   (no chain-lookup) instead of collapsing onto `SHA-256("")`. Does not
   touch `_SYNTHETIC_WRAPPER_PREFIXES`, so role classification and
   `request_jsonb` stripping are unchanged. Keys post-compact turns on
   the first real post-compact user message — stable within the session,
   distinct from the pre-compact opener, distinct across sessions.
   Normal conversations are unaffected because `messages[0]` already
   yields non-empty canonical text. Chosen.

## Decision

**Pick option 3.** Change the `first_msg_hash` computation in
`classifier.py` only:

- `classify_request` computes the hash by scanning `messages` in order,
  considering only `role == "user"` messages, and taking the first one
  whose `_canonical_user_text(content)` is non-empty. That canonical
  text is hashed (SHA-256[:16]). `_canonical_user_text` itself
  (per-message wrapper-skipping, `<session>` strip, reverse block walk)
  is unchanged.
- If no user message yields non-empty canonical text (every user
  message is wrapper-only, or `messages` is empty), `first_msg_hash` is
  `None`.
- `Classification.first_msg_hash` becomes `str | None`.
- `_resolve_conversation` skips the `_PREV_BY_HASH_SQL` chain-lookup
  when `first_msg_hash is None`, so the row uses its own `row_id` as
  `conversation_id` (a fresh conversation). The stored column holds
  `NULL` (already `nullable=True` since migration 0014 — **no migration
  required**).

The (B) chain-lookup, the (P) priority UPSERT, the (V) role vocab, and
`_SYNTHETIC_WRAPPER_PREFIXES` are all untouched.

## Consequences

- **Resolves the post-`/compact` orphaning.** Post-compact turns key on
  the first real post-compact user message → stable across the session
  → grouped into one new `conversation_id`, distinct from the
  pre-compact conversation. `/compact` now starts a new conversation,
  matching the operator's mental model.
- **The global empty-text bucket no longer receives `user_input`
  turns.** Requests with no typed text anywhere each open their own
  `conversation_id` (was: all merged onto `SHA-256("")`).
- **Normal conversations are unchanged** — `messages[0]` already yields
  non-empty canonical text, so the scan stops at it exactly as before.
  All ADR-0036 stability/collapse properties (growth-stable hash,
  `<session>` sidecar ↔ main-flow match, cache-control invariance) hold.
- **`first_msg_hash` is now `NULL` in practice** for text-less requests.
  Downstream queries that assumed it non-null must tolerate `NULL`
  (= "no groupable opener").
- **Does NOT address the identical-opener collision** (two sessions
  whose first real message is byte-identical — e.g. "반가워" — still
  fold together via the (B) rule). That is the orthogonal, pre-existing
  (B)-key weakness and is explicitly out of scope here.
- **Forward-only; no backfill.** Plugin rows persist only the delta
  (`messages[-1]`), not the full message array, so historical
  empty-bucket rows cannot have their hash recomputed — same
  irreversibility ADR-0036 noted. Existing `01KSJC53…` rows stay as-is.
- **Reversible** — pure classifier logic, revert by restoring the
  `messages[0]`-only hash. No schema dependency added.

## Open questions

- The "first real user message after compact" collides across sessions
  if two sessions' first post-compact messages are byte-identical — the
  same (B) trade-off ADR-0036 accepted. Not blocking.
- Whether to scope the orthogonal identical-opener collision (a
  session/time discriminator on the (B) key) is left to a future ADR.
