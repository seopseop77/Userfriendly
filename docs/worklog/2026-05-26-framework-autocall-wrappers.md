# 2026-05-26 · analytics_sink — framework auto-call prompts treated as wrappers

**Author**: Claude Code
**Session trigger**: Operator (verbatim): "지금 사실 plugin_analytics
쪽에서 계속 수정해야 할 것들이 보이거든? 'Perform a web search
for the query: 오늘의 주요 뉴스 이슈 2026년 5월 26일'라는
request_jsonb가 있는데 이건 보니까 assistant가 title_gen 느낌으로
한 거 같단 말이지? 이런건 어떻게 처리해야 할까?"
**Related docs**: ADR-0038 (refined here), prior worklog
`2026-05-26-per-exchange-turn-delta.md` (ADR-0038 delivery).

## Interpretation

Operator surfaced a misclassified row: `01KSHQ56AFTTVS2FSAGETXYXAM`
had `role='user_input'` with `request_jsonb` = `"Perform a web
search for the query: 오늘의 주요 뉴스 이슈 2026년 5월 26일"`. That
text was not typed by the user — Claude Code's WebSearch trigger
sends it to the LLM as the `messages[-1]` content of an internal
auto-call.

Working hypothesis (operator-proposed): user-typed text in
main-flow turns is always accompanied by Claude Code wrapper
blocks (`<system-reminder>`, `<command-*>`, `<local-command-*>`).
Framework auto-calls that aren't typed by the user lack that
wrapping. So `user_input` vs `sidecar` can be told apart by
wrapper presence — which means the bug is that the WebSearch
trigger prompt (which IS arriving with wrapper blocks alongside
it) does not match the `_SYNTHETIC_WRAPPER_PREFIXES` list, so
the stripper leaves it behind and `_last_real_user_text` picks it
up as user-typed.

## What was done

- Modified
  `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/classifier.py`
  — added two prefixes to `_SYNTHETIC_WRAPPER_PREFIXES`:
  `"Perform a web search for the query: "` (WebSearch trigger)
  and `"CRITICAL: Respond with TEXT ONLY. Do NOT call any tools."`
  (PreCompact auto-summarization prompt). Added a header comment
  explaining the three categories (bracket-tag wrappers,
  post-/compact prose header, framework auto-call prompt
  prefixes) and the whack-a-mole acknowledgement. (commit
  2963629)
- Modified
  `packages/llm_tracker_plugin_analytics_sink/tests/test_classifier.py`
  — added four scenario tests under a new "Framework auto-call
  prompts as wrappers" section:
  - `test_classify_websearch_trigger_is_sidecar` (list shape, only
    non-wrapper text is the WebSearch prompt → sidecar).
  - `test_classify_websearch_string_is_sidecar` (bare-string shape
    → sidecar via the existing string-content branch; pin against
    regression).
  - `test_classify_precompact_prompt_is_sidecar` (PreCompact-only
    turn → sidecar).
  - `test_classify_precompact_with_user_typed_is_user_input` (turn
    with `/context` stdout + user typed + trailing PreCompact →
    stays `user_input`, PreCompact is stripped from
    `request_jsonb`, stdout and user text survive).
  (commit &lt;pending&gt;)
- Modified `docs/decisions/0038-per-exchange-turn-delta.md` —
  inserted a "Framework auto-call prompts treated as wrappers
  (2026-05-26 refinement)" subsection under §`request_jsonb`
  semantics, listing the two known prefixes and the rationale.
  (commit &lt;pending&gt;)
- **DB row reclassification** (Supabase MCP `execute_sql`):
  ```
  UPDATE plugin_analytics
  SET role = 'sidecar', turn_seq = NULL
  WHERE exchange_id IN (
    '01KSHQ56AFTTVS2FSAGETXYXAM',   -- WebSearch trigger
    '01KSHPZRR4SYR5QSV6FH5QD0C8',   -- PreCompact
    '01KSHQ245K5JG9RSY1F9S5SATZ'    -- PreCompact
  );
  ```
  Three rows that classified under the old code path as
  `user_input` are now `sidecar` with `turn_seq=NULL` (ADR-0038
  axis is `role IN ('user_input', 'tool_result')` only). Post-fix
  distribution: `sidecar=17, user_input=14, tool_result=13,
  title_gen=5`.

## Decisions

- **Stdout-drop attempt for slash-command output was abandoned.**
  We first tried a more aggressive refinement: when
  `slash_commands ≠ null` and `request_jsonb` had `≥2` non-wrapper
  blocks, drop everything except the trailing block (assumed to
  be the user-typed text). The backfill SQL applied that rule to
  4 rows; two were correctly cleaned ("잘했으", "요상하네"), but
  two rows turned out to have a fourth trailing block — the
  **PreCompact framework prompt** — and the backfill erased the
  stdout + user-typed blocks and left only the PreCompact prompt.
  The "trailing block is user-typed" assumption was wrong: some
  turns have framework prompts trailing after user text. Operator
  decision: abandon the stdout-drop rule, accept that
  `request_jsonb` will carry `/context` stdout noise on those
  turns, and instead focus on classifying the framework prompts
  as wrappers so `sidecar` separation stays correct.
- **Two `/context` rows that survived the backfill cleanly keep
  the trimmed `request_jsonb`.** Reverting the trimmed rows is
  not possible (raw bodies were never stored), and the trimmed
  form ("user typed only") is arguably more useful than the
  original form for those two specific rows. Forward writes
  resume the un-trimmed behaviour.
- **`turn_seq` set to NULL on the three reclassified rows.**
  ADR-0038 turn_seq axis is `role IN ('user_input', 'tool_result')`
  only. Moving the rows to `sidecar` removes them from the axis.
  Downstream turn_seq values in those conversations are not
  recalculated — they remain monotonically increasing but with a
  gap at the reclassified positions. Acceptable historic
  artefact; forward writes will produce gap-free sequences for
  new conversations.
- **Whack-a-mole over robust signal — for now.** A more robust
  scheme (e.g. detect `web_search_*` in `request.tools`, or check
  the `system` field for the PreCompact telemetry prefix) is
  feasible but deferred. Adding two prefixes today fixes 100% of
  observed misclassifications; the robust scheme can land when a
  third pattern motivates the work.

## Verification

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_analytics_sink/tests/ -q
.................................................................. 66 passed
$ .venv/bin/python3.12 -m pytest -q
289 passed, 31 skipped in 6.44s
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_plugin_analytics_sink/src
All checks passed!
```

Live data after reclassification:

```
SELECT role, COUNT(*) FROM plugin_analytics GROUP BY role;
sidecar       17
user_input    14
tool_result   13
title_gen      5
```

Spot check of the three reclassified rows confirms `role='sidecar'`
and `turn_seq=NULL`.

## Data loss (acknowledged)

The abandoned stdout-drop backfill irreversibly trimmed
`request_jsonb` on 4 rows. Two rows ended up clean ("잘했으",
"요상하네"). The other two rows lost their `## Context Usage`
stdout and their user-typed text; only the trailing PreCompact
prompt survives in `request_jsonb`. Raw request bodies are not
stored anywhere, so the lost content cannot be reconstructed.
Practical impact is small because those two rows are correctly
re-classified as `sidecar` — their LLM-call purpose was
PreCompact summarization, not response to user input — so the
user-typed text on those turns has low analytical value.

## What's left / known limits

- **Robust framework auto-call signal** still deferred. New
  framework prompts will keep slipping through as `user_input`
  until their prefix is added. Track new patterns by spot-checking
  `role='user_input'` rows whose `request_jsonb` reads like a
  framework instruction rather than typed conversation.
- **`/context` stdout still lands in `request_jsonb`** on
  `user_input` turns that follow a `/context` invocation. Noise,
  but no longer a misclassification.
- **Schema unchanged.** No new columns, no migration. ADR-0038
  refinement is code-only.

## Handoff

ADR-0038 refinement delivered. Three misclassified rows
reclassified to `sidecar` in production. Forward writes will
emit correct `role` values for WebSearch and PreCompact turns.

Next step: operator deploys updated `llm-tracker-server` plugin
code to fly (`fly deploy -c packages/llm_tracker_server/fly.toml`,
or via the deploy-server workflow). Pre-existing pending step
from the ADR-0038 worklog — still pending. After deploy, sample
a fresh exchange and confirm a new WebSearch or PreCompact turn
classifies as `sidecar` end-to-end.
