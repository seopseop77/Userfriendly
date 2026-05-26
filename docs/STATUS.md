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

`docs/worklog/2026-05-26-framework-autocall-wrappers.md`

(Agent-stream-resilience track waiting on operator push + reinstall.
ADR-0038 deploy track still pending. See "Inactive tracks" below.)

## Recent commits (last 5)

- `<pending>` docs: backfill 2963629 hash in worklog + STATUS
- `2963629` analytics_sink: framework prompts as wrappers
- `021cc39` docs: backfill 9dee369 hash in worklog + STATUS
- `9dee369` agent: release v0.1.1 (mid-stream resilience fix)
- `f3cd704` docs: backfill afa3d59 hash + refresh STATUS

## Where we paused

**WebSearch / PreCompact auto-call prompts now classify as
`sidecar`, not `user_input`.** Operator surfaced
`request_jsonb = "Perform a web search for the query: …"` rows
landing as `user_input` — Claude Code's internal WebSearch trigger
and PreCompact summarization prompt are LLM calls the user never
typed, but the prompts arrive as plain text alongside the
existing wrapper blocks, so `_SYNTHETIC_WRAPPER_PREFIXES` did not
match them and `_last_real_user_text` picked them up.

Fix: added two prefixes to the wrapper set in `classifier.py` —
`"Perform a web search for the query: "` and `"CRITICAL: Respond
with TEXT ONLY. Do NOT call any tools."`. A turn whose only
non-wrapper text is one of those prompts now classifies as
`sidecar` (wrapper-only payload); a turn where the prompt
accompanies real user text stays `user_input` with the framework
prompt stripped from `request_jsonb`.

Live data reclassified: three rows
(`01KSHQ56AFTTVS2FSAGETXYXAM`, `01KSHPZRR4SYR5QSV6FH5QD0C8`,
`01KSHQ245K5JG9RSY1F9S5SATZ`) moved from `user_input` to
`sidecar` with `turn_seq=NULL`. New distribution:
`sidecar=17, user_input=14, tool_result=13, title_gen=5`.

A more aggressive stdout-drop refinement (drop everything but
the trailing block on `slash_commands`-attached turns) was tried,
applied as a backfill on 4 rows, and abandoned after two of the
4 rows lost their user-typed text to a PreCompact prompt that
trailed even later in the message. Two rows' content is
permanently lost. See the worklog for the full timeline.

Tests: 66 pkg / 289 repo / ruff clean.

## Next single step

**Operator deploys updated `llm-tracker-server` plugin code to
fly.** Both the original ADR-0038 schema work and this
refinement are now waiting on the same redeploy:

```
fly deploy -c packages/llm_tracker_server/fly.toml
# or push to main and let .github/workflows/deploy-server.yml run
```

After deploy, send one fresh exchange that would have
triggered the bug (any session that ends up issuing a WebSearch
or hitting PreCompact) and confirm a row lands with
`role='sidecar'`.

### Other pending push — `agent/v0.1.1`

Mid-stream upstream-close fix in `llm_tracker_agent` is committed
+ tagged but not pushed. Independent track from the
analytics_sink work above; needs:

```
git push origin main
git push origin agent/v0.1.1
# then on operator machine:
uv tool install --reinstall \
  https://github.com/seopseop77/Userfriendly/releases/download/agent/v0.1.1/llm_tracker_agent-0.1.1-py3-none-any.whl
# restart Claude Code
```

See `docs/worklog/2026-05-26-agent-stream-resilience.md` for
context.

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
