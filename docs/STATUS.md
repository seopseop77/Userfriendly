# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `CLAUDE.md §5, §6` for the rules.
>
> **Keep this file short.** Timestamp + active worklog + last 5 commits +
> where we paused + next step. History belongs in worklogs and git log.

---

**Last updated**: 2026-05-27

## Active worklog

`docs/worklog/2026-05-26-vocab-and-collapse-refinement.md`

(ADR-0038 deploy track still pending. See "Inactive tracks" below.

Side-fix landed 2026-05-27: `claude-manage` now forwards arbitrary
`claude` flags (`--dangerously-skip-permissions`, etc.). v0.1.2
shipped but had a traceback-on-exit bug; **v0.1.3 hotfix supersedes
it** — see `docs/worklog/2026-05-27-claude-manage-passthrough-args.md`
"Hotfix: v0.1.3" section. Pending operator push, then back to the
deploy track below.)

## Recent commits (last 5)

- `<pending>` agent: release v0.1.3 (typer.Exit catch hotfix)
- `53715ad` agent: catch typer.Exit (not click) in app() wrapper
- `322d53c` docs: backfill 4ad1d04 hash in worklog + STATUS
- `4ad1d04` agent: release v0.1.2 (claude-manage flag pass-through)
- `9388376` docs: backfill ded0215 hash in worklog + STATUS

**Three ADR-0038 refinements landed code-level** (no schema
change, no new ADR — §spec sections updated in place):

1. **Sidecar separation policy documented.** ADR-0038 §Sidecar
   separation signals (new section) makes the prefix-based
   wrapper-detection approach explicit, lists the three concrete
   shapes that produce `sidecar`, discusses + rejects the
   `request.tools` and `cache_control` alternatives (with the
   contract-vs-convention reasoning), and accepts whack-a-mole
   as the lower-risk trade-off.
2. **`title_gen` folded into `sidecar`.** Role vocab is now
   3-value (`user_input` / `tool_result` / `sidecar`); the
   `<session>` payload no longer gets its own role. Title
   generation is just one of several framework auto-call
   patterns and its `request_jsonb` shape stays trivially
   queryable.
3. **Rule-B collapse retired.** `extract_request_content` no
   longer collapses a single-bare-text-block list to a bare
   string. `request_jsonb` is now uniformly array for list
   content and string for string content, with no cross-pgtype
   collapse. Downstream SQL can drop the `jsonb_typeof` branch.

Earlier-this-day commit (2963629) also added `"Perform a web
search for the query: "` and `"CRITICAL: Respond with TEXT
ONLY. Do NOT call any tools."` to the wrapper-prefix list so
WebSearch / PreCompact auto-calls classify as `sidecar`. Live
data reclassified at that point: three rows from `user_input` →
`sidecar`. WebFetch result (`"\nWeb page content:\n---\n…"`) is
a third framework prompt observed once but not yet added — it
will go in with the next discovery batch.

Tests: 66 pkg / 289 repo / ruff clean.

## Next single step

**Operator deploys updated `llm-tracker-server` plugin code to
fly, then runs the two backfill UPDATEs.** ADR-0038 schema work
(121276a), framework-prompt prefixes (2963629), and this
refinement (3-value vocab + Rule-B retire) all ride the same
deploy:

```
fly deploy -c packages/llm_tracker_server/fly.toml
# or push to main and let .github/workflows/deploy-server.yml run
```

After deploy, apply two UPDATEs to align live data with the new
code (full SQL + rationale in
`docs/worklog/2026-05-26-vocab-and-collapse-refinement.md`
§"DB backfill (deferred — run after fly deploy)"):

```sql
-- Fold any historic title_gen rows into sidecar.
UPDATE plugin_analytics
SET role = 'sidecar', turn_seq = NULL
WHERE role = 'title_gen';

-- Restore array shape for user_input rows collapsed by retired Rule B.
UPDATE plugin_analytics
SET request_jsonb = jsonb_build_array(
    jsonb_build_object('type', 'text', 'text', request_jsonb #>> '{}')
)
WHERE role = 'user_input' AND jsonb_typeof(request_jsonb) = 'string';
```

Then sample a fresh `<session>` exchange and confirm it lands as
`role='sidecar'`.

### Other pending push — `agent/v0.1.3`

`agent/v0.1.2` (claude-manage flag pass-through) shipped but had
a traceback-on-exit bug: `app()` caught the upstream
`click.exceptions.Exit` while typer raises its vendored-fork
sibling, so the `typer.Exit` from `_run`'s normal exit escaped
uncaught. Live smoke caught it. `v0.1.3` is the hotfix:
catch `typer.Exit` directly, plus a real-`_run` regression test.
Committed + locally tagged; needs operator push:

```
git push origin main
git push origin agent/v0.1.3
# wait for release-agent.yml to attach the wheel, then on operator machines:
uv tool install --reinstall \
  https://github.com/seopseop77/Userfriendly/releases/download/agent/v0.1.3/llm_tracker_agent-0.1.3-py3-none-any.whl
# restart Claude Code; re-run the same smoke
# (`claude-manage --dangerously-skip-permissions` -> /quit -> no traceback)
```

See `docs/worklog/2026-05-27-claude-manage-passthrough-args.md`
"Hotfix: v0.1.3" section for context.

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
