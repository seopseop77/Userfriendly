# 2026-05-27 · analytics_sink — WebFetch result added to wrapper-prefix set

**Author**: Claude Code
**Session trigger**: Operator (verbatim): "Webfetch wrapper prefix
아직 수행 안된건가? 잘 기억이 안나네. 확인해보고 안 된거 맞으면
처리해줘."
**Related docs**: ADR-0038 (§Sidecar separation signals — defines the
prefix-based wrapper-detection approach), prior worklogs
`2026-05-26-framework-autocall-wrappers.md` (commit 2963629 — added
the first two framework prompt prefixes: WebSearch trigger, PreCompact
summarization), `2026-05-26-vocab-and-collapse-refinement.md`
("Whack-a-mole inherent" section flagged WebFetch as a known
unregistered prefix awaiting batch).

## Interpretation

Status check + a single tiny code change. The WebFetch result prefix
was documented as a known follow-up in two places (the prior
"Whack-a-mole" note + STATUS.md "Next single step") but had not been
added to `_SYNTHETIC_WRAPPER_PREFIXES`. Confirmed by `grep` against
the classifier — the existing entries cover WebSearch trigger +
PreCompact prompt only.

## What was done

- Added `"Web page content:\n---\n"` to
  `_SYNTHETIC_WRAPPER_PREFIXES` in
  `packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/classifier.py`.
  Extended the category-3 comment to cover "auto-presented content"
  (WebFetch result) in addition to "auto-call prompt" (WebSearch /
  PreCompact). (commit <pending>)
- Added two fixtures to
  `packages/llm_tracker_plugin_analytics_sink/tests/test_classifier.py`:
  - `test_classify_webfetch_result_is_sidecar` — wrapper-only
    payload (`<system-reminder>` + WebFetch result block) classifies
    as sidecar.
  - `test_classify_webfetch_with_user_typed_is_user_input` —
    user-typed block alongside a WebFetch result block keeps role
    `user_input`, with `extract_request_content` stripping the
    WebFetch block. (commit <pending>)

## Decisions

- **Prefix stored as `"Web page content:\n---\n"` (no leading
  `\n`).** `_canonical_user_text` / `_last_real_user_text` /
  `extract_request_content` all run `lstrip()` on the block text
  before `startswith()`, so any leading whitespace including newlines
  is discarded before the prefix match. The operator-observed payload
  (`"\nWeb page content:\n---\n…"`) and a version without the leading
  `\n` therefore match identically; storing the no-leading-`\n` form
  matches the style of every other entry in the tuple.
- **Internal `\n---\n` kept in the prefix.** The `---` rule is a
  literal part of the WebFetch header shape (header line, separator
  line, body). Including it tightens the match enough to avoid a
  collision with any plausible user-typed text that happens to start
  with "Web page content:".
- **Not lifted to an ADR.** ADR-0038 already accepts the whack-a-mole
  trade-off explicitly; each new prefix is an instance of that
  accepted policy, not a new decision.

## Verification

Local tests + lint:

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_analytics_sink/tests/test_classifier.py -q -k "webfetch or websearch or precompact"
6 passed, 33 deselected in 0.33s

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_plugin_analytics_sink/tests/ -q
68 passed in 0.30s
    # (was 66 before; +2 for the new WebFetch tests)

$ .venv/bin/python3.12 -m pytest -q
296 passed, 31 skipped in 6.46s

$ .venv/bin/python3.12 -m ruff check \
    packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/classifier.py \
    packages/llm_tracker_plugin_analytics_sink/tests/test_classifier.py
All checks passed!
```

Live DB backfill check (Supabase MCP `execute_sql`): zero historic
rows match the new prefix at the wrapper-check position, so no
`UPDATE … SET role = 'sidecar'` is needed.

```sql
SELECT count(*) AS would_reclassify
FROM   public.plugin_analytics
WHERE  role = 'user_input'
  AND  jsonb_typeof(request_jsonb) = 'array'
  AND  ltrim(request_jsonb #>> '{0,text}', E' \t\n\r') LIKE 'Web page content:%';
-- would_reclassify = 0
```

The operator's earlier "observed once" WebFetch row is no longer
present in `plugin_analytics` — either it predates the ADR-0038
schema (and the schema cutover dropped it) or was on a session that
never wrote through the new sink. Either way, no live rows need
reclassification.

## What's left / known limits

- **Production proxy still runs the pre-this-commit code.** The new
  prefix takes effect for new exchanges only after operator runs
  `fly deploy -c packages/llm_tracker_server/fly.toml`. Until then a
  fresh WebFetch result will continue to write as `role='user_input'`
  with the unstripped block in `request_jsonb`. Self-correcting on
  next deploy.
- **Whack-a-mole continues.** No new framework prompt patterns are
  currently on the radar. If another auto-call shape appears in the
  future, follow this same workflow (prefix + 2 fixtures +
  no-op-backfill check + worklog).

## Handoff

WebFetch follow-up closed. Next single step: operator deploys to fly
to pick up the new prefix; after that, send one WebFetch-bearing
exchange through and confirm it lands as `role='sidecar'` (or stays
`user_input` with the WebFetch block stripped from `request_jsonb`
when accompanying user-typed text).

## Suggestions (untouched)

- None — single-prefix surgical change.
