# 2026-05-28 r002 · Parallel tool_use (2-way and 3-way)

**Hypothesis**: When the assistant emits multiple `tool_use` blocks in a
single response (parallel tool calls), the follow-up user message that
delivers `tool_result`s collapses to **one** `plugin_analytics` row whose
`request_jsonb` is a list of N `tool_result` blocks — i.e. parallel
calls do not split into multiple rows and do not break the `turn_seq`
gap-free invariant.

**Conversation**: `01KSQ9BM8Z1FSDY4DBN8HARACS`
**UUID**: `276d1b70-6a27-4979-8663-ad8ac123f96b`

**Prompts sent**:

- t01: `[PROBE 2026-05-28 r002 t01] Please call Glob with pattern '*.py'
  AND Grep with pattern 'def' (output_mode count) AT THE SAME TIME in
  one parallel tool batch — do not run them sequentially. Then in one
  sentence summarize both results.`
- t02: `[PROBE 2026-05-28 r002 t02] Again, in one parallel tool batch
  (NOT sequential): (1) Glob '*.md', (2) Grep pattern 'class' with
  output_mode count, (3) Read on hello.py. All three at once.`

## Observed in supabase

| seq | role | n_blocks | in | out | cache_w | cache_r | stop | sys |
|---|---|---|---|---|---|---|---|---|
| 1 | user_input  | 1 | 3 | 161 | 4626 | 47208 | tool_use | STORED |
| 2 | tool_result | **2** | 3 | 197 |  353 | 51834 | end_turn | NULL |
| 3 | user_input  | 1 | 3 | 167 |  565 | 51834 | tool_use | NULL |
| 4 | tool_result | **3** | 3 |  66 |  956 | 52399 | end_turn | NULL |

`exchanges`: 4 rows, all 200, latencies 3–5 s. `audit_log`: standard
5-hook chain per exchange, all `outcome=ok`.

## Findings

1. **Parallel tool_use collapses into a single sink row.** Row 2's
   `request_jsonb` is a 2-element list (Glob result + Grep result with
   distinct `tool_use_id`s); row 4 is a 3-element list (Glob + Grep +
   Read). `turn_seq` increments by exactly 1 in each case (1→2, 3→4) —
   no split, no gap.
2. **`role = 'tool_result'` on multi-block content.** The 3-value
   classifier (ADR-0038) treats a content list whose every block is a
   `tool_result` as `tool_result`. Matches the documented rule.
3. **Glob-empty result is still a tool_result row.** Row 4 block 1 is
   `{type: tool_result, content: "No files found"}` — Claude Code returns
   a string body, classifier still routes to `tool_result`. No false
   sidecar.
4. **Server-side prompt cache hits *across* conversations.** Row 1 of
   r002 already shows `cache_read_tokens = 47208` even though
   `conversation_id` is brand new. The Anthropic prompt cache is server-
   side prefix-hash based; running r002 immediately after r001 in the
   same workdir means most of the system prompt + tool registrations
   tokenise identically, so the cache hits. **Implication for analysis:
   "first row of a round has cache_read=0" is only true on a cold
   workdir / cold system.** Within a back-to-back campaign this
   assumption is wrong — must verify chain semantics within-round
   rather than expecting cold opens.
5. **No segfault on `new` this round.** r001 t01 (`new`) segfaulted with
   exit 139; r002 t01 (`new`) exited 0. Non-deterministic, no obvious
   correlate. Will keep tallying across rounds.

## Anomaly tracker
- r001 segfault candidate: still **not reproduced** in r002. Status:
  open, low-frequency.

## Score
- ✅ row count = 4 (2 user × 2 tool-rounds)
- ✅ all rows same conversation_id
- ✅ turn_seq 1→4 gap-free
- ✅ role correct on every row (multi-block tool_result is `tool_result`)
- ✅ cache chain valid (within-round; cross-round inheritance is a
  separate observation, not a bug)
- ✅ `system_prompt_jsonb` STORED on row 1 only
- N/A E-track baits
