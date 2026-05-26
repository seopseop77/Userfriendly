# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-05-26

## Active worklog

`docs/worklog/2026-05-26-agent-stream-resilience.md`

(ADR-0038 track paused — see "Inactive tracks" below.)

## Recent commits (last 5)

- `<pending>` docs: backfill afa3d59 hash + refresh STATUS
- `afa3d59` agent: swallow mid-stream upstream close in proxy
- `3fe4044` docs: backfill 00cc2b0 hash + refresh STATUS
- `00cc2b0` analytics_sink: strip x-anthropic-billing-header
- `4694b30` docs: backfill 121276a hash in worklog + STATUS

## Where we paused

**Mid-stream upstream-close in `llm_tracker_agent` no longer
crashes the proxy.** `proxy.py:body_iter` was only wrapping
`aiter_bytes()` in `try/finally`; any `httpx.RemoteProtocolError`
(or sibling) raised after streaming had started bubbled up as an
ASGI 500 and printed a long uvicorn traceback on every occurrence.
Operator saw it firing reliably around Claude Code's `/context`
and other background calls.

Fix: added `except _UNREACHABLE_ERRORS: return` inside
`body_iter`'s `try` block. Status + headers have already shipped
by the time the generator runs, so we can't degrade to 503 the
way we do at initial `send()` time — the right move is to
terminate the generator cleanly. Downstream client receives the
partial bytes that already made it across; uvicorn no longer
emits the traceback.

Coverage: new `test_swallows_midstream_upstream_close` in
`packages/llm_tracker_agent/tests/test_proxy.py` exercises the
exact failure path via a custom `AsyncByteStream` that yields one
chunk then raises `RemoteProtocolError`.

Tests: 10 pkg / 285 repo / ruff clean.

## Next single step

**Operator reinstalls the uv tool and restarts Claude Code.** The
traceback originates from
`/Users/minseop/.local/share/uv/tools/llm-tracker-agent/...`,
which is a separate wheel install from the workspace source.
The source-level fix only takes effect after:

```
uv tool install --reinstall ./packages/llm_tracker_agent
```

(or the equivalent from `2026-05-25-uv-tool-install.md`),
followed by restarting Claude Code so the new agent process
loads. After that, retry `/context` — the uvicorn traceback
should no longer appear.

If the traceback persists, the file path in the new traceback
tells us whether the installed copy actually refreshed.

---

## Inactive tracks

### ADR-0038 per-exchange turn delta — awaiting fly deploy

Active worklog: `docs/worklog/2026-05-26-per-exchange-turn-delta.md`.
ADR-0038 delivered and applied live. `conversation_messages`
and the `plugin_analytics_with_messages` helper view are retired;
per-exchange turn deltas now live directly on `plugin_analytics` in
three new columns:

- `role` (text, ADR-0038 4-value vocab: `user_input` / `title_gen`
  / `tool_result` / `sidecar`) replaces `turn_kind`.
- `request_jsonb` (jsonb) stores `messages[-1].content` with
  session-opener wrappers stripped; no `{role, content}` envelope.
- `system_prompt_jsonb` (jsonb) stores `request.system` only when
  it differs from the conversation's most recent non-null stored
  system (first exchange or variation).

`response_json` (text) cast + renamed to `response_jsonb` (jsonb).
`n_messages_at_request` dropped. `classify_message` /
`split_first_message` (the per-message classifier surface of
ADR-0037) retired in favour of one role per exchange.

ADR-0036, ADR-0037: Status `Superseded by ADR-0038`.

- Live migration applied via Supabase MCP `execute_sql`:
  - ADD COLUMN role / request_jsonb / system_prompt_jsonb.
  - DROP VIEW plugin_analytics_with_messages.
  - ALTER + RENAME response_json → response_jsonb.
  - UPDATE backfill of request_jsonb + role from
    conversation_messages.
  - DROP COLUMN turn_kind, n_messages_at_request.
  - DROP TABLE conversation_messages.
  - UPDATE alembic_version → `0019_per_exchange_turn_delta`.
- Final state: 16 rows / 0 missing role / 0 missing request_jsonb.
  role distribution: user_input 3 / title_gen 2 / tool_result 5 /
  sidecar 6. `system_prompt_jsonb` NULL on all historic rows (raw
  bodies not retained — forward writes populate).

**Follow-up refinement** (this checkpoint): variation tracker was
firing on every exchange because Anthropic surfaces a per-request
`x-anthropic-billing-header:` block inside the system field whose
`cc_version` / `cch` tokens drift across calls. Added
`classifier.normalize_system` which strips that prefix; both
`_system_hash` and `_resolve_system` pipe through it (hash + stored
form), preserving the invariant "same hash ⇒ identical stored
bytes". ADR-0038 §system_prompt_jsonb semantics updated. No new
migration — historic rows already NULL.

- Tests: 62 pkg / 284 repo / ruff clean.

**Pending operator step**: deploy updated plugin code to fly
(`llm-tracker-server`). The new schema is live but the production
proxy still runs the ADR-0036 code path, which writes to columns +
tables that no longer exist. Until deploy,
`analytics_sink.insert_failed` will appear in structlog for every
new exchange; the proxy itself stays healthy (plugin failures are
caught defensively). After deploy, send one exchange through the
proxy and confirm a row lands with `role` and `request_jsonb`
populated.

### scope_guard

Paused at `0c1ca9d`. Code-complete on Gemini (ADR-0031) but no live
smoke. Separate owner. Do NOT auto-resume.
Production: `fly secrets set LLMTRACK_PLUGINS_DISABLED=scope_guard -a llm-tracker-server`

### Participant-#1 install

Back-burner, waits on signup-app redeploy. See ADR-0035 follow-up
in `docs/worklog/2026-05-25-uv-tool-install.md`.
