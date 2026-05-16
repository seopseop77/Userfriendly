# 2026-05-17 · Archive sidecar + superseded ADRs (housekeeping)

**Author**: Claude Code
**Session trigger**: User-provided two-task housekeeping prompt: (1) move 7
superseded ADRs into `docs/decisions/archive/`; (2) preserve and remove
`packages/llm_tracker/` (the original local sidecar, superseded by
`llm_tracker_server` + `llm_tracker_agent` per ADR-0017).
**Related docs**: ADR-0017 (central-server deployment model),
ADR-0029 (consent + scrubber, prior session), `docs/STATUS.md`.

## Interpretation

Task 1 was unambiguous — move 7 named ADR files, update the README,
verify the listing.

Task 2 carried two latent issues that needed clarification:

1. The user described `packages/llm_tracker/` as "fully isolated legacy
   — zero imports from `llm_tracker_server` or `llm_tracker_agent`." That
   covers one direction. The opposite direction was not clean:
   - `packages/llm_tracker_plugin_supabase_sink/tests/test_e2e.py`
     imports from `llm_tracker.plugin_host.host`,
     `llm_tracker.egress_guard.guard`, `llm_tracker.storage.models`.
   - Five other test files inside `packages/llm_tracker/tests/` import
     only from `llm_tracker_sdk` (the kept package) — they were
     misplaced test files for currently-shipped SDK code, including
     the freshly-added ADR-0029 scrubber and accessor-wiring tests
     (commit `a4c08b3`, 2026-05-17).
2. The user's step 1 said "create `archive/local-sidecar` and push it";
   the closing line said "do not push either branch — humans push."
   CLAUDE.md §10 forbids auto-push.

Both surfaced via `AskUserQuestion`. User picks:
- Archive `supabase_sink` alongside the sidecar (its workstream closed
  2026-05-08 per STATUS; the only sidecar-tied surface was its e2e test).
- Rescue the 5 SDK-only test files into
  `packages/llm_tracker_sdk/tests/` and add that path to
  `[tool.pytest.ini_options].testpaths`.
- Do NOT push `archive/local-sidecar`.

## What was done

### Task 1 — archive superseded ADRs (commit `8ef166d`)

- Created `docs/decisions/archive/`.
- `git mv` 7 superseded ADRs into the archive:
  - `0001-python-fastapi-httpx.md`
  - `0004-central-server-stack.md`
  - `0006-egress-policy-and-deployment-modes.md`
  - `0007-central-server-as-optional-plugin.md`
  - `0008-plugin-signing-trust-model.md`
  - `0016-user-opt-in-env-knob.md`
  - `0021-retire-plugin-manifest-signing.md`
- `docs/decisions/README.md` — appended an `## archive/` section
  explaining the directory is historical-only.

Verification: `ls docs/decisions/` shows only active ADRs (0002, 0003,
0005, 0009–0015, 0017–0020, 0022–0029) + `archive/` + `README.md` +
`TEMPLATE.md`.

Outbound link audit: `grep -rE "docs/decisions/(0001|0004|0006|0007|0008|0016|0021)-" --include="*.md"` flagged 11 references — all inside frozen
worklog narratives. Left alone per CLAUDE.md §2.3 (surgical changes;
worklogs are historical records of past sessions).

### Task 2 — remove llm_tracker local sidecar (commit `3d76d1f`)

- Created local branch `archive/local-sidecar` at HEAD before any
  deletions, so it preserves the full repo state including
  `packages/llm_tracker/` and `packages/llm_tracker_plugin_supabase_sink/`.
  Not pushed.
- Deleted `packages/llm_tracker/` entirely (35 source files + 17 test
  files; 3 alembic migrations).
- Deleted `packages/llm_tracker_plugin_supabase_sink/` entirely (6
  source files + 4 test files).
- Rescued 5 SDK-only test files from `packages/llm_tracker/tests/` into
  `packages/llm_tracker_sdk/tests/` — git auto-detected them as
  renames:
  - `test_egress_protocol.py` — imports `llm_tracker_sdk` only.
  - `test_harness.py` — imports `llm_tracker_sdk.testing` (`PluginHarness`).
  - `test_hook_context.py` — imports `llm_tracker_sdk.HookContext`,
    `ContentLevel` (includes the 4 ADR-0029 accessor-wiring tests).
  - `test_manifest.py` — imports `llm_tracker_sdk.manifest`.
  - `test_scrubbers.py` — imports `llm_tracker_sdk.scrubbers.scrub`
    (16 ADR-0029 scrubber unit tests).
- `pyproject.toml` `[tool.pytest.ini_options].testpaths`:
  - Removed `packages/llm_tracker/tests`.
  - Removed `packages/llm_tracker_plugin_supabase_sink/tests`.
  - Added `packages/llm_tracker_sdk/tests`.
- `uv.lock` — `uv sync` dropped `llm-tracker`,
  `llm-tracker-plugin-supabase-sink`, and `respx` (the latter was only
  needed by sidecar/supabase_sink tests).
- `[tool.uv.workspace].members` left untouched — it uses the
  `packages/*` glob, so removed packages disappear automatically.

## Decisions

- **Archive `supabase_sink` too** (vs delete just its e2e test). The
  package's runtime depends on `llm_tracker_sdk` + `structlog` only, but
  STATUS records its workstream as closed 2026-05-08, superseded by
  the server-side `analytics_sink`. Keeping it for one runtime that
  nobody runs while its only e2e dies anyway adds drag for no gain.
  `archive/local-sidecar` preserves it.
- **Rescue 5 SDK-only test files** rather than let them die with the
  sidecar. They test currently-shipped SDK code (`llm_tracker_sdk.*`).
  The 12 other test files (everything importing `llm_tracker.cli`,
  `llm_tracker.proxy`, `llm_tracker.plugin_host`, `llm_tracker.config`,
  `llm_tracker.storage`, `llm_tracker.content_levels`,
  `llm_tracker.egress_guard.client`/`guard` plus the
  `llm_tracker_plugin_host`-mixed tests) legitimately go with the
  sidecar.
- **Do not push `archive/local-sidecar`.** CLAUDE.md §10 forbids
  auto-push; the user's closing instruction confirmed it. The branch
  is local-only; the operator pushes when ready.
- **Outbound link cleanup in worklogs deferred.** 11 historical
  worklog files reference the moved ADR paths. Worklogs are frozen
  narratives; rewriting them mixes scope and erases the snapshot of
  what the path was at the time.

## Verification

```
$ ls docs/decisions/
0002-task-scope-enforcement.md
0003-distribution-strategy.md
0005-framework-first-plugin-architecture.md
0009-allowed-modes-required-non-empty.md
0010-block-abort-plugin-field.md
0011-transform-policy.md
0012-hook-context.md
0013-plugin-disable-config.md
0014-plugins-introspection.md
0015-egress-client-sdk.md
0017-central-server-deployment-model.md
0018-multi-tenancy-per-org-rls.md
0019-mode-taxonomy-retired-content-level-kept.md
0020-auth-per-org-token-anthropic-passthrough.md
0022-deployment-platform-fly-supabase.md
0023-server-auth-header-rename.md
0024-agent-fallback-fail-closed.md
0025-agent-language-python-cli.md
0026-hookcontext-response-accessors.md
0027-exchange-row-close-out-policy.md
0028-extractor-faithful-response-reassembly.md
0029-consent-data-handling.md
README.md
TEMPLATE.md
archive

$ ls docs/decisions/archive/
0001-python-fastapi-httpx.md
0004-central-server-stack.md
0006-egress-policy-and-deployment-modes.md
0007-central-server-as-optional-plugin.md
0008-plugin-signing-trust-model.md
0016-user-opt-in-env-knob.md
0021-retire-plugin-manifest-signing.md

$ git branch --list "archive/*"
  archive/local-sidecar

$ uv sync 2>&1 | tail -8
Resolved 60 packages in 324ms
   Building llm-tracker-plugin-keyword-block @ ...
Prepared 1 package in 190ms
Uninstalled 4 packages in 5ms
Installed 1 package in 1ms
 - llm-tracker==0.0.1 (uninstalled)
 - llm-tracker-plugin-supabase-sink==0.1.0 (uninstalled)
 - respx==0.23.1 (uninstalled)

$ .venv/bin/python3.12 -m pytest -q
143 passed, 16 skipped in 5.68s
```

The 143-pass count is the no-DB baseline. Before this housekeeping:
338 passed no-DB (per STATUS, post-ADR-0029). Delta = 195 tests gone
with the sidecar + supabase_sink as intended; the 5 rescued files
contribute back ≈55 tests (counted as the diff between 88 pre-rescue
and 143 post-rescue).

DB-fixture test count was not re-run in this session — the rescued
SDK tests are pure unit tests that don't need the DB fixture, and no
sidecar tests previously required it (those would be the now-deleted
proxy tests). The 354 → ~159 DB-fixture count drop expected at next
run; no information loss because the deleted tests cover deleted code.

Secrets scan on the staged diff:

```
$ git diff --cached | grep -E "(Bearer |sk-|AKIA|ghp_|xoxb-|password=|LLMTRACK_.*_TOKEN=)"
-                headers={"x-api-key": "sk-ant-test", ...}
-    assert route.calls[0].request.headers.get("x-api-key") == "sk-ant-test"
-            (b"x-api-key", b"sk-client"),
-    assert sent.headers.get("x-api-key") == "sk-client"
-            return Transform(headers={"x-api-key": "sk-rewritten"})
```

All hits are fixtures in deleted test files (lines prefixed `-`). No
real secrets touched.

## What's left / known limits

- `archive/local-sidecar` is local-only. Operator pushes manually when
  ready: `git push -u origin archive/local-sidecar`.
- The 11 historical worklog references to moved ADR paths are now
  broken links if rendered as HTML. Acceptable per CLAUDE.md §2.3 (do
  not rewrite frozen narratives).
- DB-fixture count not re-measured this session — only the no-DB
  count was checked, since rescued tests are SDK-pure unit tests.

## Handoff

Housekeeping landed; no operator action owed by this session. The
unchanged next blocking item from the prior session stands:

> **Operator deploy of `a4c08b3` to Fly** to pick up the ADR-0029
> scrubber on production traffic (no code-side changes; the next
> `fly deploy` picks up the new SDK that `analytics_sink` already
> imports).

Cleanest single thing for the next session: confirm that ADR-0029
operator-deploy has happened (a fresh `plugin_analytics` row carries
`[REDACTED:…]` tags in `request_text` / `response_content_json` per
`docs/plugins.md` §3.2). If yes, ADR-0029 closure flips from
"shipped, awaiting deploy" to "live in production."

## Suggestions (untouched)

- The 11 worklog files with broken ADR-path references could be
  swept in a single docs-only commit if the team wants live HTML
  rendering. Out of scope today.
- `packages/llm_tracker_sdk/` had no `tests/` directory before this
  commit. The newly created path is a natural home for any future
  SDK-only test files — the rescue establishes the convention.
