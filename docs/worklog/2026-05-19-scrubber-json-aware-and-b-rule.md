# 2026-05-19 · PII scrubber JSON-aware + conversation_id (B) rule

**Author**: Claude Code
**Session trigger**: "손상된 부분 전부 수정하고 다시 알려줘" — operator noticed
plugin_analytics rows missing after the second-scenario stress session
(22:22–22:27 KST).
**Related docs**: `docs/decisions/0029-consent-data-handling.md` (scrubbers
contract); prior worklog `2026-05-19-turn-classification-refinement.md`.

## Interpretation

Two coupled bugs surfaced together:

1. The PII scrubber's regex ran over JSON-encoded text and the email
   pattern's `\b` word boundary matched between a literal `\` and the
   `t` of a `\t` JSON escape — consuming the `t` into
   `test_user@example.com`. After substitution the orphan `\`
   collided with the leading `[` of `[REDACTED:email]`, producing
   `\[` which is not a valid JSON escape.
2. `AnalyticsSink._PREV_BY_HASH_SQL` cast `messages_json::jsonb` to
   read message count. The (1) corruption made that cast fail. The
   plugin's `except Exception` swallowed the exception and rolled
   back every new INSERT whose chain lookup hit a corrupted prior
   row — silently dropping rows from `plugin_analytics`.

Fixed both in one pass. Also applied the (B) conversation_id rule the
operator had already greenlit ("(B)가 내 의도랑 맞는거라서 (B)로 가는
게 좋을 듯") — it removes the JSONB-cast dependency entirely and aligns
`conversation_id` semantics with the operator's mental model ("one
Claude Code session = one conversation until /compact or /clear").

## What was done

- Modified `packages/llm_tracker_sdk/src/llm_tracker_sdk/scrubbers.py` —
  added a JSON-aware fast path: when the input parses as JSON, walk
  the structure, scrub each *decoded* string value, then
  re-serialise via `json.dumps(..., ensure_ascii=False,
  separators=(",", ":"))`. Falls back to flat-text scrubbing for
  non-JSON input. Eliminates the orphan-backslash hazard at the root.
- Modified
  `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py`:
  - `_PREV_BY_HASH_SQL` simplified to `SELECT conversation_id` only.
    Dropped the `messages_json::jsonb -> 'messages'` extraction +
    `length(messages_json)` cast. Side-effect: invulnerable to any
    historic body that fails JSONB cast.
  - `_LAST_SEQ_IN_CONV_SQL` rewritten to `MAX(turn_seq)` — gives a
    cumulative per-conversation step counter that survives
    out-of-order INSERTs.
  - `_resolve_conversation` simplified to **(B) rule**: same
    `first_msg_hash` in the same org always inherits the prior
    `conversation_id`; no prior row → new conversation. `turn_seq`
    becomes `MAX + 1` over `(user_input_turn_start ∪
    tool_continuation)` rows.
- Updated tests:
  - `packages/llm_tracker_sdk/tests/test_scrubbers.py` — three new
    cases: `test_scrub_json_body_remains_valid_json`,
    `test_scrub_json_orphan_backslash_regression` (the exact
    `77\ttest_user@example.com\n78` shape that broke prod), and
    `test_scrub_falls_back_to_text_for_non_json_input`.
  - `packages/llm_tracker_plugin_analytics_sink/tests/test_analytics_sink.py`
    — adjusted two cases for (B):
    `test_tool_continuation_inherits_conversation_id` (unchanged
    expectation, comment refresh) and renamed
    `test_identical_first_prompt_after_clear_starts_new_conversation`
    → `test_identical_first_prompt_inherits_under_b_rule` with
    flipped assertions.
- Applied **live data repair** via Supabase MCP `execute_sql`:
  - Repaired 89 rows whose `messages_json` (and where applicable
    `response_json`) contained the orphan-backslash pattern
    `\[REDACTED:...]`. SQL:
    `REPLACE(messages_json, E'\\[REDACTED:', E'\\\\[REDACTED:')`
    scoped by the same LIKE predicate.
  - Verified: all 117 rows in `plugin_analytics` now cast cleanly to
    JSONB (msgs_castable=117, resp_castable=117).
  - Backfilled the 117 historic rows under the (B) rule
    (conversation_id = first row of each `(first_msg_hash, org_id)`
    cluster by `created_at`; cumulative `turn_seq` over
    user_input_turn_start + tool_continuation only) — 56 rows
    updated to new conv ids / turn_seqs; the rest already matched
    the (B) shape.

## Decisions

- **JSON-aware scrubbing over regex-level fixes**: a stricter
  `(?<!\\)\b` lookbehind would have suppressed the orphan-backslash
  case but at the cost of missing legitimate matches that happen to
  appear right after a literal backslash. JSON-aware operates on
  decoded values where there are no JSON escapes to confuse the
  regex.
- **(B) inheritance unconditional on prev hash match**: per the
  operator's "동일한 프롬프트로 인해서 생기는 문제는 일단 감수해야
  할 것 같아" — two genuinely-separate sessions sharing an identical
  first prompt fold into one conversation. Cleaner than the (A)
  message-count heuristic that the data showed splitting one Claude
  Code session into several conv ids whenever an
  `internal_subprompt` inflated the prev row past the next user
  turn.
- **`turn_seq` semantics shift**: now cumulative within a
  conversation rather than reset-per-user-turn. Carries more
  information; the per-turn step can be derived as the run from one
  `user_input_turn_start` to the next.
- **Historic data repaired in place** rather than dropped or
  shadow-tabled. Side-effect: scrubber output for those rows is
  now `\\[REDACTED:...]` (JSON-valid; decodes to `\[REDACTED:...]`)
  rather than the pre-bug ideal where the scrubber would have
  produced just `[REDACTED:...]` without the orphan `\` at all.
  Information-equivalent for analysis purposes.

## Verification

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_sdk \
    packages/llm_tracker_plugin_analytics_sink \
    packages/llm_tracker_server -q
147 passed, 18 skipped in 5.58s

$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_sdk \
    packages/llm_tracker_plugin_analytics_sink
All checks passed!
```

Live DB sanity (Supabase MCP):

```
total           : 117
msgs_castable   : 117   ← was failing pre-repair on ~89 rows
resp_castable   : 117
```

## What's left / known limits

- **Operator action: `fly deploy` from `main`** — the new image must
  carry the JSON-aware scrubber + the simplified plugin SQL before
  the next live exchange, or new rows will continue to be written
  with the orphan-`\[` shape and `_PREV_BY_HASH_SQL` will keep
  failing for the duration of the rollout. Without redeploy the
  historic repair is undone the moment a new exchange lands.
- The Read tool / file-content path through Anthropic's API is the
  only confirmed orphan-backslash source so far. A 1-week production
  audit after redeploy will tell us whether the JSON-aware path
  catches everything; if any new `\X` (X∉escape) shows up, the
  fallback flat-text path is the next suspect.
- **No new ADR needed**: the (B) rule is an implementation refinement
  of ADR-0007's analytics design, not a public-contract change. The
  scrubber fix sits behind the ADR-0029 contract — input/output
  invariants unchanged for plugins.

## Handoff

Next active step is operator-side `fly deploy`. After redeploy, a
single in-session multi-scenario stress run (separate doc) regenerates
the data needed for the `conversation_messages` dedup design's
normalisation-whitelist study. The 4-scenario plan from the prior
worklog still applies but the operator asked for it re-packaged so
all four can run inside a single Claude Code session without
fragmenting prompt cache — see the response message for the
condensed form.

## Suggestions (untouched)

- The `messages_json` column would be a natural candidate for
  `jsonb` typing rather than `text`, now that every row is
  guaranteed parseable. Defer to the same migration that introduces
  `conversation_messages` (the dedup table) where `messages_json`
  is being dropped anyway.
