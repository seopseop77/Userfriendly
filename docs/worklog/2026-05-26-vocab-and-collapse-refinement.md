# 2026-05-26 · analytics_sink — fold title_gen into sidecar, retire Rule-B collapse

**Author**: Claude Code
**Session trigger**: Operator (verbatim, condensed): "옵션 A로 가자
[prefix-based wrapper detection을 유지하고 cache_control은 안 쓴다].
대신 sidecar 분류에 대한 이야기를 좀 명시적으로 적어둘 필요는
있을 듯. 그리고 아까 말했던 것처럼 title_gen도 그냥 sidecar로
바꿔주고, 마지막으로 그 {text, type:text} 형태는 그냥 plain text로
풀어서 저장을 한다고 한 거 같은데, 통일성이 너무 없어서 그냥 이
경우에도 안 풀고 저장하는 게 좋을 거 같은데, 그렇게 안하는 이유라도
있나?"
**Related docs**: ADR-0038 (refined here), prior worklogs
`2026-05-26-per-exchange-turn-delta.md` (ADR-0038 delivery),
`2026-05-26-framework-autocall-wrappers.md`
(prefix-based wrapper detection, commit 2963629).

## Interpretation

Three independent refinements landed together in one session:

1. **Sidecar separation policy documented.** The prefix-based
   wrapper-detection approach (rather than a more robust signal
   like `request.tools` inspection or `cache_control` presence)
   is now explicitly justified in ADR-0038. The whack-a-mole
   trade-off is acknowledged; switching to a robust signal is
   deferred until a Claude Code change invalidates several
   prefixes at once.
2. **`title_gen` folds into `sidecar`.** Title generation is one
   of several Claude Code framework auto-call patterns and gives
   no analytic signal that warrants its own role; querying for
   the `<session>...</session>` shape remains a one-line content
   filter against `request_jsonb`. The role vocab is now 3-value:
   `user_input` / `tool_result` / `sidecar`.
3. **Rule-B collapse retired.** The single-bare-text-block →
   bare-string collapse in `extract_request_content` gave a
   visually cleaner storage shape for short turns but split the
   `request_jsonb` column between `jsonb_typeof = 'string'` and
   `'array'`, forcing downstream SQL to handle both. Operator
   observation: "통일성이 너무 없어서…그렇게 안하는 이유라도
   있나?" — there wasn't a strong reason. Removed.

## What was done

### Code (classifier.py)

- `MessageRole` Literal: drop `"title_gen"` → 3-value.
- `classify_message`: `<session>` string-content branch returns
  `sidecar` (not `title_gen`); single-block list with a
  `<session>...</session>` payload returns `sidecar`. Module
  docstring + branch comments updated.
- `extract_request_content`: removed the single-block collapse
  branch. List content with a single surviving non-wrapper block
  now stores as a one-element list, matching the multi-block
  case. Function docstring updated to explain the change.

(commit f9197cd)

### Tests (test_classifier.py, test_analytics_sink.py)

- `test_classify_message_session_string_is_title_gen` →
  `..._is_sidecar`; assertion changed to `"sidecar"`.
- `test_classify_message_session_single_block_list_is_title_gen`
  → `..._is_sidecar`; same.
- `test_extract_strips_leading_wrappers_and_collapses_single_block`
  renamed to `test_extract_strips_leading_wrappers`; assertion
  changed to list-shape (`out[0]["text"] == "hello"`).
- `test_extract_strips_command_wrappers_too`: assertion changed
  to list-shape.
- `test_extract_single_block_bare_text_collapses_to_string`
  renamed `_stays_array`; assertion changed to
  `[{"type": "text", "text": "first"}]`.
- `test_extract_drops_cache_control_keys` renamed
  `_single_block_with_cache_control_stays_array`; assertion
  changed to list-shape preserving `cache_control`.
- `test_title_gen_string_classifies_correctly` →
  `test_session_string_classifies_as_sidecar`; role assertion
  `sidecar`; `request_jsonb` stays a string (string content
  path, not affected by collapse change).
- `test_title_gen_list_shape_classifies_correctly` →
  `test_session_list_shape_classifies_as_sidecar`; role
  assertion `sidecar`.
- `test_row_written_on_persisted_with_parsed_response`:
  `request_jsonb` assertion changed from `"hi"` to
  `[{"type": "text", "text": "hi"}]`.
- `test_session_opener_wrappers_stripped_from_request_jsonb`:
  same, `"hello"` → list shape; docstring updated.

(commit f9197cd)

### ADR-0038

- `§role vocab` table reduced from 4 rows to 3 (title_gen row
  removed); refinement note added explaining the fold.
- `§request_jsonb semantics` `Non-opener exchanges` note
  updated: "Rule A retired, and Rule B's single-bare-text-block
  collapse retired 2026-05-26 for storage-shape uniformity".
- **New section `§Sidecar separation signals`** added: the
  three concrete shapes that produce `sidecar`, an explicit
  acknowledgement that signal is prefix-based pattern matching
  (deliberate), the `request.tools` and `cache_control`
  alternatives discussed and rejected (with operator's exact
  reasoning about contract vs convention), the trade-off
  acceptance ("keep adding prefixes when new framework prompts
  appear (whack-a-mole)"), and the current registered prefix
  list verbatim.
- `§Reconstruction queries — Sidecars for C`: `role IN
  ('title_gen', 'sidecar')` → `role = 'sidecar'`.
- `§Migration` `title_gen → title_gen` mapping note expanded to
  document the 2026-05-26 fold (live data reclassified to
  `sidecar` in a subsequent UPDATE).
- `§Consequences` first bullet: "4-value classifier" → "3-value
  classifier".

(commit f9197cd)

## Decisions

- **Prefix-based wrapper detection retained over robust signal**
  (operator-decided). Robust alternatives considered:
  - `request.tools` content (WebSearch / WebFetch are
    server-tools; their presence in tools list is a candidate
    signal). Deferred — Anthropic API guarantees are weaker than
    the wrapper-prefix convention we already rely on.
  - `cache_control` presence on the user-typed block (operator's
    observation: every typed block carries it, every framework
    block does not). Rejected — `cache_control` is a general
    API optimisation knob; Claude Code's attachment policy is a
    convention, not a contract. A classifier depending on it
    could silently mis-route user input into `sidecar` if Claude
    Code changes its caching policy (the more harmful
    direction).
  - Acceptance: whack-a-mole on prefixes is the lower-risk
    path; revisit robust-signal question if a future Claude
    Code change ever invalidates several prefixes at once.
- **Fold `title_gen` into `sidecar` rather than keeping it.**
  Operator-decided. Title generation behaves identically to
  other framework auto-calls (LLM call not initiated by user
  typing); separating it as its own role offered no decision
  signal that wasn't recoverable with a one-line content
  filter (`request_jsonb::text LIKE '<session>%'`).
- **Retire Rule-B collapse rather than keep the bare-string
  shape.** Operator-decided. The collapse was inherited from
  ADR-0036/0038's hash-collapse rule for `_canonical_user_text`,
  but `extract_request_content` storage shape is separate from
  hash semantics. The collapse split `request_jsonb` between two
  pgtypes (string vs array), which forced downstream SQL to
  branch on `jsonb_typeof` for nearly every query. Operator
  preferred storage uniformity over the marginal readability
  gain on short turns.
- **No new ADR.** All three refinements fit within ADR-0038's
  scope (per-exchange schema + `role` vocab + `request_jsonb`
  semantics). The §spec sections were updated in place. A
  separate ADR would have been warranted if any of the three
  had touched the schema or the public hook lifecycle.

## Verification

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_analytics_sink/tests/ -q
66 passed in 0.37s

$ .venv/bin/python3.12 -m pytest -q
289 passed, 31 skipped

$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_plugin_analytics_sink/src packages/llm_tracker_plugin_analytics_sink/tests
All checks passed!
```

## DB backfill (deferred — run after fly deploy)

The production proxy still runs the pre-2963629 code path (and
this refinement on top of it). Two UPDATEs to apply after
`fly deploy -c packages/llm_tracker_server/fly.toml`:

```sql
-- 1. Fold any historic title_gen rows into sidecar.
UPDATE plugin_analytics
SET role = 'sidecar', turn_seq = NULL
WHERE role = 'title_gen';

-- 2. Restore array shape for user_input rows that were collapsed
--    by the retired Rule B. (Only rows where the original block
--    had `cache_control = NULL` — the only shape that triggered
--    collapse — became string-stored, so the back-conversion is
--    a clean `{type, text}` reconstruction.)
UPDATE plugin_analytics
SET request_jsonb = jsonb_build_array(
    jsonb_build_object('type', 'text', 'text', request_jsonb #>> '{}')
)
WHERE role = 'user_input' AND jsonb_typeof(request_jsonb) = 'string';
```

Running these before deploy creates a brief inconsistency: the
production proxy would write new string-form user_input rows
under the old code while pre-deploy backfilled rows are
array-form. The window is short and forward writes resolve once
the new code is live.

`sidecar` rows whose `request_jsonb` is a bare string are
**not** rewritten — they were always string from the
RAW-message-content path (not the collapse path), so the bare
string is the correct stored shape.

## What's left / known limits

- **Deploy still pending.** Same fly deploy that the prior
  framework-prompts commit (2963629) and the ADR-0038 schema
  work (121276a) are waiting on. Until then production rows
  classify under the pre-deploy code (no framework prefix list,
  with `title_gen` role, with Rule-B collapse).
- **Whack-a-mole inherent.** New framework auto-call prompts
  will need their prefix added when discovered. Currently
  registered: WebSearch trigger, PreCompact prompt. Future
  candidates: WebFetch trigger (operator observed once; prefix
  not yet added — left as a deliberate sample so the new
  prefix gets added together with the next discovery batch).
- **No `cache_control` monitoring metric.** A defensive
  signal — log when a row's `cache_control` distribution
  disagrees with the prefix-based classification — was
  considered (option D in the design discussion) and shelved.
  Worth revisiting if whack-a-mole maintenance grows
  burdensome.

## Handoff

Three refinements delivered, all code-level, no schema change.
Next single step: operator runs the existing `llm-tracker-server`
fly deploy (covers all three pending commits), then applies the
two `UPDATE` statements above against the live DB. After deploy,
sample a fresh `<session>` exchange and confirm it lands as
`role='sidecar'`.

## Operator follow-through (2026-05-27)

Operator completed the deploy + backfill. Verified live via
Supabase MCP `execute_sql` from this session:

```sql
SELECT count(*) FILTER (WHERE role = 'title_gen')                                 AS leftover_title_gen,
       count(*) FILTER (WHERE role = 'user_input' AND jsonb_typeof(request_jsonb) = 'string') AS leftover_user_input_string,
       count(*) AS total_rows,
       max(created_at) AS latest_exchange_ts
FROM   public.plugin_analytics;
-- leftover_title_gen=0, leftover_user_input_string=0,
-- total_rows=35, latest_exchange_ts=2026-05-27 06:55Z.
```

Both backfill UPDATEs ran cleanly. Fresh `<session>` opener
written by the live proxy at 2026-05-27 06:43Z landed as
`role='sidecar'` with array-shape `request_jsonb` — confirms
the new code path (framework-prompt prefixes + 3-value vocab
+ Rule-B retired) is serving on fly. `request_jsonb` distribution
across the 35 rows: `user_input` 13 (all array), `tool_result` 9
(all array), `sidecar` 10 (7 array + 3 bare string from the
RAW-message-content path — expected). Track closed. (commit c599d08)
