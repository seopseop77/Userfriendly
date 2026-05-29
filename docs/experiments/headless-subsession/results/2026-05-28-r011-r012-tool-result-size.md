# 2026-05-28 r011 + r012

## r011 · Large tool_result (partial)

**Intent**: force a Bash tool_result of ≥ 100 kB to test
`request_jsonb` storage for size-related truncation / anomaly.

**Result**: **inconclusive on size — the model refused to invoke
the tool.** Both attempts (t01 and the explicit "you MUST invoke"
retry) ended with `stop_reason: end_turn` and *no* `tool_use` emission.
Two `user_input` rows, no `tool_result` row.

| seq | role | stop | out_tokens |
|---|---|---|---|
| 1 | user_input | end_turn |  454 |
| 2 | user_input | end_turn |  158 |

**Findings**:
1. **Sonnet self-skips tool calls when it judges the output as
   excessively large (or just describable).** Even with explicit
   "MUST invoke" framing the model preferred to answer textually.
   Worth noting if a future probe wants to *guarantee* a large
   tool_result — pick a tool whose result the model cannot predict
   (e.g., Read of an opaque file it hasn't seen), and keep the user
   prompt phrased as a question that requires fresh data.
2. **No truncation observed across earlier rounds** for tool_result
   content up to ~3 kB (r007 WebSearch body, r005 t02 50-object JSON).
   No upper bound established here, but no anomaly either.
3. **`turn_seq` increments on consecutive `user_input` rows** when
   the model never produces a tool_use → the axis is "any
   main-flow message," not "alternating user/tool" — matches
   ADR-0038's `_TURN_AXIS_ROLES = {user_input, tool_result}` rule.

## r012 · Chain-of-tool autonomous — covered by r004

The hypothesis ("model-initiated chain of multiple tool calls within
one user prompt all land as separate plugin_analytics rows with
consistent conversation_id") was verified directly by **r004 t01**:
Read → Edit → Bash, 4 contiguous rows, same conversation_id,
`turn_seq` 1→2→3→4 gap-free, terminating row carrying
`stop_reason: end_turn`. Retired without a fresh round.
