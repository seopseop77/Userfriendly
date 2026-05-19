# 2026-05-19 — turn classification refinement + analytics_sink miss

Follow-up track to `2026-05-19-turn-classification.md`. After the
operator's `fly deploy` shipped migration 0014's classifier live,
hand-testing surfaced two issues that the original implementation
did not anticipate. Both are addressed here as one atomic fix.

## Request

> "지금 그래서 fly deploy까지 했고, 테스트를 좀 해봤는데, 결과가 맞는지
> 잘 모르겠네? […] supabase mcp 써서 분석을 한 번 해봐."

Operator's hand-test: 5 typed inputs + 2 slash commands; expected to
see 5 `user_input_turn_start` rows, observed 3.

## Interpretation

Two distinct issues mixed into one symptom:

1. **Mislabel.** Claude Code's per-session title-generation call (the
   small "Generate a concise, sentence-case title" request that
   accompanies every new conversation) was being tagged
   `claude_manage_probe` because its content always ends with the
   user's first message wrapped in `<session>...</session>`. The label
   name suggested a probe from the `claude-manage` agent, but those
   rows are really Claude Code internal sub-prompts. Visible in 8
   historic rows.
2. **Sink miss.** Exchange `01KRZARYVBNAN9XCPNB8N8BAVT` (14:19:11
   KST, status 200, latency 9085 ms, content_level L3) appears in
   `exchanges` and the framework-level `audit_log` shows all five
   hooks (`on_request_received` … `on_persisted`) firing `ok` for it,
   but no row landed in `plugin_analytics`. The plugin's
   `on_request_received` early-returns silently when
   `ctx.request_text()` is None — which the SDK docstring permits:
   "the request body has not yet been provided to this context (e.g.
   a hook firing before the forwarder reads the body)". When that
   happens, `on_persisted` finds nothing in `_stash` and also
   silently returns. No row, no log, no audit trail.

Both are independent and addressed in one code change + one live
backfill.

## What was done

Code half shipped in commit `98fbe9e`.

### Classifier — system-prompt-aware title-gen detection

- `classifier.py` — added two substring constants and a `_system_text`
  helper that flattens the request's `system` field (string or list
  of `{type:"text", text:"…"}` blocks) into one string for sniffing.
  Renumbered rules: a new **Rule 2** fires first — if the system text
  contains `"Generate a concise, sentence-case title"`, the request
  is Claude Code's per-session title fetch → `internal_subprompt`.
  The old `<session>` wrapper rule (now Rule 5) was narrowed to fire
  only when Claude Code is **not** the originator (no
  `"You are Claude Code"` in system). In production every `<session>`
  call rides Claude Code, so Rule 5 is effectively dead code now —
  the label stays in the `TurnKind` union for the offline / out-of-
  band probe case but the SQL backfill below produces zero rows
  bearing it.
- `tests/test_classifier.py` — added 4 cases:
  - `test_title_generation_call_is_internal_subprompt` (system signal
    wins over `<session>` user wrapper)
  - `test_claude_code_with_session_wrapper_is_real_user_turn`
    (`<session>` in a real Claude Code call is just the user's text)
  - `test_step_away_recap_is_internal_subprompt` (the
    `"The user stepped away"` recap arrives as `content`=string and
    is already caught by the string-content rule — explicit test for
    regression protection)
  - `test_title_generation_system_field_string_form` (system field
    accepted as a plain string, not only block list)

### analytics_sink — fallback recovery + observability

- `plugin.py — on_request_received`: when `ctx.request_text()`
  returns None, emit a `analytics_sink.stash_skipped` structlog
  warning carrying the `exchange_id`. Used to be silent.
- `plugin.py — on_persisted`: when no stash entry is found, try
  `ctx.request_text()` once more — the forwarder typically finishes
  populating the raw body before `on_persisted` even if it had not
  by `on_request_received`. On success, emit
  `analytics_sink.persist_fallback_recovered`. On failure, emit
  `analytics_sink.persist_skipped` with `reason=no_request_body` —
  no longer silent. `ctx.org_id is None` warning gained the
  `exchange_id` field for searchability.
- `tests/test_analytics_sink.py` — added 2 cases:
  - `test_persist_fallback_recovers_when_body_arrives_late` (body
    None at first hook, set before `on_persisted` → row IS written
    via the fallback path)
  - `test_persist_skipped_when_body_never_arrives` (body never
    arrives → no INSERT, no exception)

### Live backfill

One in-place `UPDATE` via Supabase MCP `execute_sql`, scoped to rows
whose `system` field contains the title-gen signature and currently
labeled `claude_manage_probe`. Returned 8 row ids; post-state
verified:

| `turn_kind`            | rows before | rows after |
|------------------------|------------:|-----------:|
| `tool_continuation`    |          30 |         30 |
| `internal_subprompt`   |          12 |         20 |
| `user_input_turn_start`|          17 |         17 |
| `claude_manage_probe`  |           8 |          0 |

`turn_seq` was already NULL on the affected rows (both
`claude_manage_probe` and `internal_subprompt` are off-turn-axis),
so no further fixup was needed. `conversation_id` is also untouched
— the chain-lookup uses `first_msg_hash`, which the label does not
gate.

## Decisions

- **Title-gen → `internal_subprompt`, not a new label.** The prior
  worklog deliberately kept the vocabulary to four labels and
  carried sub-classifications in side columns (`slash_commands`,
  `messages_json`). Title-gen detection follows the same principle —
  it's a Claude Code internal call, so it belongs with the existing
  internal bucket. The system-text signature is queryable directly
  from `messages_json` if someone needs to split title-gen out later.
- **`claude_manage_probe` label kept in the union, vocabulary frozen
  at four.** Zero rows carry it post-backfill, but a real offline
  probe (claude-manage hitting the proxy without Claude Code) would
  still find its slot. Removing the label outright would have been
  a vocabulary change touching downstream queries; the conservative
  choice is to leave it.
- **Fallback recovery in `on_persisted`, not retry / dead-letter.**
  The SDK docstring is explicit that `request_text()` can return
  None at hooks firing before the forwarder reads the body —
  re-trying once at `on_persisted` (where the body is always
  available) is the minimal recovery path that fits the SDK
  contract. A retry queue or dead-letter table would be an ADR-
  level decision; this fix gets us out of the silent-failure mode
  without committing to that.
- **No DB-level audit row from the plugin for skips.** Plugin-level
  `audit_log` writes would be more durable than structlog (which
  goes to Fly stdout) but require expanding the SDK's audit API.
  Out of scope here; the structlog warnings get us 90 % of the way
  with zero new surface area.

## Verification

```
$ .venv/bin/python -m pytest packages/llm_tracker_plugin_analytics_sink/tests/ -v
collected 28 items
.........................27 passed in 0.13s
```

Was 26 before this change; +4 classifier cases, +2 plugin cases,
−2 reshape (one existing test refactored, one trimmed). Net 28
passing.

```
$ .venv/bin/python -m pytest \
    packages/llm_tracker_plugin_analytics_sink/tests/ \
    packages/llm_tracker_server/tests/ \
    packages/llm_tracker_sdk/tests/ -q
142 passed, 18 skipped in 5.55s
```

Up from 140 in the prior worklog. Skip count unchanged (DB-fixture
gated).

```
$ .venv/bin/python -m ruff check --output-format=concise \
    packages/llm_tracker_plugin_analytics_sink
All checks passed!
```

### Live backfill verification

```sql
SELECT turn_kind, count(*) FROM public.plugin_analytics
GROUP BY turn_kind ORDER BY count DESC;
-- tool_continuation        30
-- internal_subprompt       20
-- user_input_turn_start    17
-- (claude_manage_probe:     0)
```

### Cross-check against the hand-test

Operator's 14:08~14:44 KST session re-mapped under the new rules:

| # | typed input          | row(s)                                  | turn_kind                              |
|---|----------------------|-----------------------------------------|----------------------------------------|
| 1 | STATUS.md ㄱㄱ        | 14:08:02 (title-gen) + 14:08:08 + …      | `internal_subprompt` + `user_input_turn_start` + continuations |
| 2 | follow-up queue      | 14:10:39                                | `user_input_turn_start`                |
| 3 | `/clear`             | (no API call — client-side only)        | —                                      |
| 4 | RLS                  | 14:11:53 (title-gen only)               | `internal_subprompt` (was `claude_manage_probe`) |
| 5 | Supabase             | 14:14:45 + 14:15:26 + 14:15:29 + 14:17:01 | `user_input_turn_start` + title-gen + /compact summarize |
| 6 | `/compact`           | 14:17:01 (summarize call)               | `internal_subprompt`                   |
| 7 | 반가워               | 14:19:11 (sink miss — pending re-test)  | (no row yet — fallback fix will recover after redeploy) |
| — | step-away recap      | 14:44:12                                | `internal_subprompt`                   |

The "missing" inputs from the operator's perspective resolve as:
RLS reached Claude Code's title-gen but never produced a main-
conversation call in this session (data-side issue, not classifier);
반가워 was sink-missed and recovered by the new fallback path
(re-test after `fly deploy`).

## What's left / known limits

- **`fly deploy`** is the operator step. Until that ships, new rows
  will keep using the old classifier path on production. The
  backfill above already handles the historic 67 rows.
- **Sink-miss root cause** still unconfirmed without Fly logs. The
  fallback path recovers transparently and the new warnings make
  any future miss visible. If `fly logs … | grep analytics_sink`
  shows `stash_skipped` paired with `persist_fallback_recovered`
  consistently, the underlying timing is real and we leave it.
  If it shows `persist_skipped reason=no_request_body`, the body is
  never readable in either hook — a deeper bug that needs separate
  investigation.
- **RLS main-conversation call** at 14:11~14:14 KST is genuinely
  absent from `exchanges` (not just `plugin_analytics`). Either
  claude-manage didn't issue the call or it failed before the proxy
  saw it. Out of scope for this worklog — flag in STATUS for the
  next session to look at if the pattern reproduces.

## Handoff

Code half is ready to ship. Operator action: `fly deploy` from
`main` after the commits below. Smoke verification path: run the
same kind of session (a few normal inputs, a /clear, a /compact,
exit) and confirm:

1. Every typed user input that reaches Claude Code's main conversation
   produces exactly one `user_input_turn_start` row in
   `plugin_analytics`.
2. Title-gen rows are labeled `internal_subprompt` (not
   `claude_manage_probe`).
3. If `analytics_sink.stash_skipped` shows up in Fly logs, the
   corresponding exchange should still produce a row via the
   `persist_fallback_recovered` path.

## Suggestions (untouched)

- The classifier's `_TITLE_GEN_SIGNATURE` is a substring of Claude
  Code's title prompt today. If Anthropic ships a CC version that
  rewords the title prompt, every new title-gen row will silently
  go back to looking like a user turn. Consider a unit test that
  re-scans the latest production data at CI time and flags any row
  whose `turn_kind` would flip under the current rules — same idea
  as the earlier worklog's prefix-list rot concern, just extended
  to the system-text signal.
- Plugin-level `audit_log` writes (`analytics_sink.stash_skipped`
  → audit row) would survive container restarts where structlog
  output is gone. SDK API expansion required; track separately.
