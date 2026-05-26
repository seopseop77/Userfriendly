# ADR-0037 · Display role vocab — split system_prompt / user_input, name title_gen, merge sidecars into assistant

- **Status**: Superseded by ADR-0038
- **Date**: 2026-05-25
- **Author**: Claude Code (operator-directed)
- **Related**:
  - Worklog: `docs/worklog/2026-05-25-display-role-vocab.md`
  - Supersedes the `conversation_messages.role` vocabulary defined by
    ADR-0036 (V). The `classify_request` / `TurnKind` vocabulary on
    `plugin_analytics.turn_kind` is unchanged.
  - Touches `conversation_messages.role` semantics — listed under
    CLAUDE.md §9 public interfaces.

## Context

ADR-0036 (V) moved `conversation_messages.role` from the API protocol
values (`user`/`assistant`) onto a per-message origin vocabulary that
reused `TurnKind` plus one extra `assistant` value:

```
user_input_turn_start, tool_continuation, internal_subprompt,
claude_manage_probe, assistant
```

Operator inspection of live rows (2026-05-25, 246 stored messages,
37 distinct conversations) surfaced three usability gaps:

1. **The session-opener row is hard to read.** Claude Code's first
   request of a session sends `messages[0]` as a list whose leading
   blocks are `<system-reminder>` (agent catalog, CLAUDE.md, etc.)
   followed by the user's typed text. Stored as a single
   `user_input_turn_start` row, the user's actual question is hidden
   inside ~30 kB of synthesised framing. Searching the dedup table
   for "what did the user open with?" requires text-stripping every
   first row.

2. **`internal_subprompt` covers two very different things.** The
   bucket holds (a) Claude Code's per-session **title-generation**
   sidecar (small, one-shot, `<session>...</session>`-wrapped) and
   (b) heavyweight framework prompts: `/compact` summarize,
   `[SUGGESTION MODE: ...]` autocomplete, the step-away recap. An
   analyst grouping by `role` cannot tell them apart without
   pattern-matching the content again.

3. **`assistant` is overloaded with `role=assistant`.** The display
   value `assistant` carries the model's real response. The
   per-message origin vocab piled tool_continuations and the model's
   own turn under the same label is fine for joins
   (`cm.role = pa.turn_kind`) but visually ambiguous when reading
   conversation rows top-to-bottom.

Defect 1 is structural (one stored row hides two semantic units);
defects 2 and 3 are naming choices. Operator direction (2026-05-25):
ship all three in one vocab refresh.

## Options considered

1. **Status quo + UI-side prettification.** Leave the table alone;
   teach downstream readers (web inspector, analyst notebooks) to
   strip wrappers and pattern-match. Defers complexity to every
   consumer. Rejected.

2. **Split + 5-role vocab (chosen).** One coordinated change:
   - Peel `messages[0]`'s leading wrapper blocks into a separate row
     with role `system_prompt`; the user's typed text lands at
     `msg_index=1` with role `user_input`. Subsequent API messages
     shift +1.
   - Split `internal_subprompt` into `title_gen` (the
     `<session>...</session>` shape only) and `assistant` (everything
     else Claude Code synthesises with `role=user`).
   - Rename `assistant` → `model_output` for the model's response;
     keep `assistant` as the bucket for Claude Code-synthesised
     non-title-gen messages (tool_continuation, /compact summarize,
     SUGGESTION MODE, step-away recap, post-`/compact` resume
     marker).
   - Drop `claude_manage_probe` from the display vocab (it was dead
     code in production — claude-manage proxies Claude Code's own
     requests). The `TurnKind` enum keeps it for parity at the
     request-classification layer.

3. **Add a separate `system_prompt_jsonb` column on
   `conversation_messages`.** Keeps `msg_index` 1:1 with the API
   `messages[]` array. Rejected per operator preference for the row
   split: easier to query top-to-bottom, no schema migration, the
   wrapper content stays inspectable.

4. **Add `cm.kind` parallel column; keep `role` as API protocol.**
   Two columns to interpret instead of one richer field. Rejected
   for the same reason ADR-0036 rejected its variant of this.

## Decision

**Pick option 2.** The display vocab on `conversation_messages.role`
becomes:

| Role | Source | Notes |
|---|---|---|
| `system_prompt` | Splitter on `messages[0]` only | Wrapper blocks (`<system-reminder>`, `<command-name>`, `<local-command-*>`, post-`/compact` resume marker, …) peeled off the first message. |
| `user_input` | `classify_message` | List content with at least one non-wrapper text block; *or* the user-input slice of a split `messages[0]`. |
| `title_gen` | `classify_message` | String content whose payload is `<session>...</session>`. Claude Code's per-session title fetch. |
| `model_output` | `classify_message` | `role=assistant` messages. |
| `assistant` | `classify_message` | Every other framework-synthesised `role=user` message: tool_result continuations, `/compact` summarize string, SUGGESTION MODE string, step-away recap string, list content with only synthetic wrappers. |

**`msg_index` shift rule.** When `messages[0]` carries leading
wrapper blocks (split applies):

- `msg_index = 0` → role=`system_prompt`, content=wrapper blocks
  (list preserved).
- `msg_index = 1` → role=`user_input`, content=remaining blocks
  (normalised; a single bare text block collapses to a string per
  ADR-0036 Rule B).
- Subsequent API messages occupy `msg_index = 2, 3, …`.
- `plugin_analytics.n_messages_at_request` is bumped by +1 so the
  helper view's `WHERE cm.msg_index < pa.n_messages_at_request`
  filter still captures every stored row for that exchange.

When the split does not apply (string content, single bare block,
list with no leading wrapper, list with only wrappers, or
`role != "user"`), the mapping is the original 1:1 — `msg_index = N`
for `messages[N]`, no `n_messages_at_request` bump.

**Priority UPSERT.** Updated to a single sidecar candidate:

```sql
ON CONFLICT (conversation_id, msg_index) DO UPDATE
SET role = EXCLUDED.role,
    content_jsonb = EXCLUDED.content_jsonb
WHERE conversation_messages.role = 'title_gen'
  AND EXCLUDED.role IN (
    'system_prompt', 'user_input', 'model_output', 'assistant'
  )
```

`title_gen` is the only Claude Code sidecar that lands at the same
`msg_index` (= 0, or = 1 after split) where the main flow will later
write the real `user_input`. Other former-`internal_subprompt`
shapes (`/compact`, SUGGESTION MODE, step-away) occupy fresh indexes
deeper in the conversation and never collide with real content under
the new vocab.

**Backfill.** A Python script under
`packages/llm_tracker_plugin_analytics_sink/scripts/` reads the live
246 historic `conversation_messages` rows and:

1. Reclassifies every row's `role` from the ADR-0036 vocab to the
   ADR-0037 vocab using the same `classify_message` /
   `split_first_message` helpers the plugin uses forward.
2. For each `msg_index=0` row whose content is a list with a leading
   wrapper block, deletes the original row, inserts a
   `system_prompt` row at `msg_index=0` and a `user_input` row at
   `msg_index=1`, and shifts every other row in the same
   `conversation_id` by +1.
3. Bumps the matching `plugin_analytics.n_messages_at_request`
   value by +1 for exchanges affected by the shift.

The script is idempotent (already-shifted conversations no-op) and
runs in dual `--emit-sql` / `--apply` mode like ADR-0036's backfill.

## Consequences

- **Resolves defect 1.** The session-opener's wrapper framing and
  the user's first typed question live on adjacent rows; a top-to-
  bottom read of `conversation_messages` is human-legible without
  text-stripping.
- **Resolves defect 2.** `title_gen` separates from `assistant` —
  filter / GROUP BY on `role` no longer needs to pattern-match the
  body.
- **Resolves defect 3.** `model_output` names the model's turn;
  `assistant` names framework-synthesised `role=user` continuations.
  Naming matches the prevalent operator mental model.
- **`cm.role = pa.turn_kind` joins no longer line up symbolically.**
  ADR-0036 leaned on the equivalence to keep analyst queries simple.
  Affected queries (none in tree as of 2026-05-25) must update to a
  CASE / mapping. The TurnKind enum at the request layer is
  unchanged so `plugin_analytics.turn_kind` rows are untouched.
- **`n_messages_at_request` is no longer "count of API messages."**
  It is now "count of stored `conversation_messages` rows visible to
  this exchange." Identical for unsplit exchanges; +1 for split
  exchanges. The helper view (`plugin_analytics_with_messages`)
  continues to work without change because its filter is
  `cm.msg_index < pa.n_messages_at_request` — the row count, which
  is what we just preserved.
- **`claude_manage_probe` dropped from the display vocab.** The
  `MessageOrigin` Literal lost it; production data never had a
  message-level value of this label. `TurnKind` retains it for the
  rare offline claude-manage probe — `plugin_analytics.turn_kind`
  rows that carry the value are unaffected.
- **Forward writes use raw-message classification.** `classify_message`
  runs on the un-normalised message dict, so a single bare
  `{type:"text",text:"X"}` array reaches `_last_real_user_text` as a
  list and classifies as `user_input` (then normalises to a bare
  string on storage). The backfill's path is different — it reads
  already-normalised rows and uses pattern matching on the string
  case (carried over from ADR-0036's backfill).
- **Reversible.** A downgrade backfill (re-merge `system_prompt` +
  `user_input` into one row, shift indexes back, restore the
  ADR-0036 vocab) is straightforward to write but unlikely needed.

## Open questions

- **`/compact` resume marker rows.** A `messages[0]` whose only
  blocks are the post-`/compact` resume marker (`This session is
  being continued from a previous…`) plus `<system-reminder>` has
  no non-wrapper text, so `split_first_message` returns `None` and
  the row classifies as `assistant`. That feels semantically off
  (this is not really an assistant message), but no clear better
  bucket exists in the 5-value vocab. Acceptable: the row's actual
  payload is preserved and a future ADR can carve out a
  `compact_resume` value if usage justifies it.
- **Forward-data drift.** Operators inspecting a conversation
  pre-backfill see the old vocab; post-backfill, the new one.
  The backfill is a single MCP `execute_sql` run; gap is minutes.
