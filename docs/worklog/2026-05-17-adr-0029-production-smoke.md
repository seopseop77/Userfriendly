# 2026-05-17 · ADR-0029 production smoke — scrubber verified, docs reconciled

**Author**: Claude Code
**Session trigger**: STATUS.md "Next single step" — operator deploy of
`a4c08b3` (ADR-0029 scrubber) to Fly, followed by post-deploy verification
on production `plugin_analytics` rows.
**Related docs**: ADR-0029 (consent + data-handling),
ADR-0028 (faithful response reassembly), `docs/plugins.md` §3.2,
`packages/llm_tracker_sdk/src/llm_tracker_sdk/hook_context.py`,
`packages/llm_tracker_plugin_analytics_sink/src/llm_tracker_plugin_analytics_sink/plugin.py`,
prior worklog `docs/worklog/2026-05-17-adr-0029-consent.md` (which this
worklog corrects on one factual point).

## Interpretation

Two threads in flight:

1. **Verification thread (planned).** Confirm the ADR-0029 scrubber takes
   effect on real production traffic after `fly deploy` of commit `a4c08b3`.
2. **Drift recovery (unplanned).** `claude-manage` returned `command not
   found` immediately after the deploy; the agent package was still
   editable-installed (`uv pip list` showed `llm-tracker-agent`), but the
   console_script entry-point in `.venv/bin/` had gone missing. Tracked
   back to yesterday's housekeeping (`uv sync` after the sidecar +
   supabase_sink drops), which dropped three packages and silently
   skipped the agent's script regeneration.

Both threads converged into a single finding: the scrubber works, *and*
in working it falsifies a single assumption baked into ADR-0029 +
ADR-0028 + `docs/plugins.md` + the SDK module docstring + the prior
ADR-0029 worklog — namely that `analytics_sink` parses request bodies
on its own path and therefore that `public.plugin_analytics` carries
canonical (unscrubbed) bodies. The plugin actually reads through
`ctx.request_text()` / `ctx.response_content_json()`, both of which run
`scrub()` before returning. The on-disk row therefore inherits the
scrubbed shape; the docs claimed the opposite.

The user's call (Option A on the resolution interview): align the docs
to production behaviour and keep the privacy-first posture. No code
change to plugins or accessors.

## What was done

- **`uv sync --reinstall-package llm-tracker-agent`** — restored
  `.venv/bin/claude-manage`. Verified: `-rwxr-xr-x` script + `--help`
  returns the `setup` command. (no commit; environment-only fix.)
- **Production smoke** — user injected `sk-deadbeef12345678` in a
  request body through `claude-manage` on Fly release `v11` (the
  ADR-0029 image, deployed ~16m before the smoke). Two `200 OK`
  `plugin_analytics` rows landed within ~2s of each other:
  - `01KRRS5S2VNPPCS5QNM4P2HG37` (end_turn, 16:16:10 UTC)
  - `01KRRS5PJGVDK4J6XND3JWKCEH` (end_turn, 16:16:08 UTC)
- **SQL verification** (Supabase MCP `execute_sql`):
  - `messages_json ~ 'sk-deadbeef12345678'` → **false** on both rows.
  - `messages_json ~ '\[REDACTED:secret\]'` → **true** on both rows.
  - `response_json ~ 'sk-deadbeef…'` → false (Anthropic did not echo it
    in either response).
  - Conclusion: the scrubber is live and is reaching the database row
    written by `analytics_sink`.
- **Code path tracing**:
  - `analytics_sink/plugin.py:113` —
    `body = ctx.request_text()` (not raw body parsing).
  - `_build_row` (same module) —
    `"response_json": ctx.response_content_json()`.
  - `hook_context.py:120` — `return scrub(decoded)` on `request_text`.
  - `hook_context.py:188` — `return scrub(value)` on
    `response_content_json`.
  - The path is unambiguous: every `plugin_analytics` row inherits the
    scrubbed shape on both columns.
- **Doc reconciliation** (this worklog's commit):
  - ADR-0029 §"Axis 6" body — replaced the "storage layer keeps the
    canonical body" paragraph with an explicit split between server-core
    writes (`public.exchanges`: metadata only) and plugin-mediated writes
    (`public.plugin_analytics`: scrubbed via the accessor). Net effect:
    no on-disk canonical body exists today.
  - ADR-0029 §"Open questions" — the `messages_json` fidelity bullet
    rewritten as "Canonical-body retention for incident response", since
    the previous bullet was the load-bearing wrong claim. The new bullet
    documents the (intentional) absence of a canonical-body surface and
    names the future ADR that would re-introduce one if needed.
  - ADR-0028 §"Open questions" — added a 2026-05-17 update clarifying
    that the scrubber landed at the SDK accessor, not as a
    post-extractor pass, so the extractor's faithful-reassembly contract
    governs the in-memory `_parsed_response` only, not the row written
    by the current plugin.
  - `docs/plugins.md` §3.2 — replaced the "storage layer reads the
    canonical body" paragraph with the actual production behaviour
    (server-core table = metadata only; plugin-written table =
    scrubbed). Plugin authors querying the DB directly now have correct
    expectations.
  - `hook_context.py` module docstring — same correction applied to the
    SDK docstring so a plugin author reading the SDK source has the
    same picture.
  - `docs/worklog/2026-05-17-adr-0029-consent.md` §"What's left" —
    appended a `> **Correction (2026-05-17, …)**` blockquote under the
    incorrect `messages_json` bullet. Frozen-narrative rule from
    CLAUDE.md §2.3 preserved: the original bullet is untouched, the
    correction notes when and how it was overturned.

## Decisions

- **Docs align with production, not the other way around** (user's
  resolution choice). The scrubber is intentionally at the accessor;
  pushing it any deeper into storage would not change anything since
  the plugin already reads through the accessor. Pushing it shallower
  (moving it out of the SDK) would silently strip the protection from
  any future plugin that joins.
- **No new ADR.** The correction is an amendment in place of ADR-0029
  rather than a follow-up ADR. The `Decisions` section's six axes did
  not change — only the descriptive paragraph under Axis 6 and one
  bullet in "Open questions" were factually wrong. Splitting that into
  a new ADR would obscure the policy by indirection.
- **No ADR-0028 status change.** The faithful-reassembly contract for
  the extractor is intact. Only the comment-level prediction
  ("`extractor → scrubber → storage` once the scrubber lands") about
  the future order was wrong. Captured as an Update note in §"Open
  questions" rather than a Supersedes.
- **No backfill, no migration.** The mistaken claim was descriptive,
  not load-bearing for schema. The actual production rows have been
  scrubbed since `v9` (2026-05-16 17:05 UTC) — by then the SDK
  scrubber was already live. The pre-`v9` rows from 5月 13 do not
  carry an injected secret to scrub anyway; they predate the
  consent ADR.
- **`packages/llm_tracker/` + `packages/llm_tracker_plugin_supabase_sink/`
  empty directory shells** observed during the diagnosis — left in
  place. `git rm` removed the files; the directories themselves are
  not tracked and not causing any behaviour difference. A `rmdir` of
  the two empty directories is a separate one-line follow-up if the
  user wants the tree clean.

## Verification

```
$ uv sync --reinstall-package llm-tracker-agent | tail -5
 ~ llm-tracker-agent==0.0.1 (from file:///…/packages/llm_tracker_agent)

$ ls -la .venv/bin/claude-manage
-rwxr-xr-x@ 1 minseop  staff  349 May 17 01:06 .venv/bin/claude-manage

$ .venv/bin/claude-manage --help
Usage: claude-manage [OPTIONS] COMMAND [ARGS]...
  setup  Write central-server URL + token to ~/.llm-tracker/config.toml.
```

Fly deploy timing (confirms which image processed the smoke):

```
$ fly releases -a llm-tracker-server | head -3
 VERSION │ STATUS   │ DESCRIPTION │ USER                  │ DATE
 v11     │ complete │ Release     │ minseopgod7@gmail.com │ 16m24s ago
 v10     │ complete │ Release     │ minseopgod7@gmail.com │ 11h18m ago
```

`v11` is the ADR-0029 image (commit `a4c08b3`). Smoke ran ~16m after
deploy.

Supabase SQL (verbatim observed):

```
plugin_analytics row 01KRRS5S2VNPPCS5QNM4P2HG37 (created_at 2026-05-16 16:16:10 UTC):
  messages_json ~ 'sk-deadbeef12345678' → false
  messages_json ~ '\[REDACTED:secret\]' → true
  response_json ~ '\[REDACTED:secret\]' → false  (model did not echo)

plugin_analytics row 01KRRS5PJGVDK4J6XND3JWKCEH (created_at 2026-05-16 16:16:08 UTC):
  same shape; mj_has_redacted_secret = true, mj_has_raw_dummy = false
```

Code-path inspection results captured in §"What was done".

## What's left / known limits

- **Empty package-directory shells** under
  `packages/llm_tracker/` and `packages/llm_tracker_plugin_supabase_sink/`.
  Cosmetic only; no behaviour impact. `rmdir` if the user wants the
  tree clean — one line of work.
- **`plugin_analytics` RLS** — Supabase advisor still flags this table
  (along with `orgs`, `api_tokens`, `alembic_version`) as RLS-off. The
  three substrate tables were an intentional choice (CP13-b §Decisions
  4) but `plugin_analytics` was added in migration 0007 *after* that
  decision; it is not on the documented "intentionally RLS-off" list.
  Queued as a separate follow-up CP.
- **Server-core canonical-body surface** — if a real operator
  incident-response use case emerges, a dedicated write path
  (independent of SDK accessors) can persist canonical bytes under a
  shorter retention. Tracked in ADR-0029 §"Open questions".
- **`exchanges.tool_call_count` fate** and **pre-SSE
  upstream-failure-path row write** (ADR-0027 axis 2 impl) remain
  queued from prior closures.

## Handoff

CP commits, in order:

```
d7f17c0   docs: reconcile ADR-0029 storage-canonical with prod
<finalize>   docs: STATUS + worklog — ADR-0029 production smoke
```

External (non-team) testing of the central server is now fully ready to
proceed: ADR-0029 is policy, the scrubber is operationally verified on
the live image, and the descriptive docs match what the database
actually carries. The "operator-deploy" step that was the last
operational gate before external testing is complete.

The remaining queued follow-ups (none gating any next CP):

- `plugin_analytics` RLS enablement (newly-surfaced; not in the
  CP13-b intentional list).
- Empty package-directory shells `rmdir`.
- ADR-0027 axis 2 impl (pre-SSE upstream-failure-path row write).
- `exchanges.tool_call_count` fate.
- Real `session_id` populator + deletion endpoint.
- Automated 6-month retention deletion job.
- i18n email scrubbing.
