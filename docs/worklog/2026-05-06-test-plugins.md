# 2026-05-06 · Test plugins (token_counter + keyword_block)

**Author**: Claude Code
**Session trigger**: User asked to build two **TEST-ONLY** plugins before
opening Phase 1c, to verify what the framework already supports end-to-end:
(1) count input/output/cache tokens and write to a DB; (2) block requests
containing forbidden keywords.
**Related docs**: `docs/plugins.md`, `docs/decisions/0006-egress-policy-and-deployment-modes.md`,
`docs/decisions/0008-plugin-signing-trust-model.md`,
`docs/decisions/0012-hook-context.md`

## Interpretation

The framework still has gaps the canonical "plugin writes to its own DB
namespace" path depends on (`HookContext` has no DB accessor; the proper
Extractor is Phase 2). The user explicitly chose **option A**: each test
plugin is self-contained and writes to its own sidecar SQLite under
`var/`. They will be removed once their core-feature replacements land
(Phase 2 Extractor for token_counter, Phase 1c `scope_guard` for the
block-path verification). Both packages, all docstrings, and both
manifests must mark themselves as **test-only / verification-only** so
nobody is tempted to depend on them.

## What was done

- Created `packages/llm_tracker_plugin_token_counter/` — TEST-ONLY plugin
  that aggregates Anthropic SSE `usage` events (`message_start` +
  `message_delta`) and writes one row per exchange to a sidecar SQLite at
  `var/plugin_token_counter.db` (override via
  `LLMTRACK_PLUGIN_TOKEN_COUNTER_DB`). Hooks: `on_response_chunk`,
  `on_response_complete`, `on_shutdown`. Capabilities:
  `read_response_metadata`, `read_response_content`. Three modules:
  `__init__.py` (plugin class), `parser.py` (SSE buffer +
  `UsageAccumulator`), `storage.py` (`UsageStore` + `UsageRecord` over
  aiosqlite). 10 unit tests in `tests/test_token_counter.py`. Manifest
  signed by `minseop`. (commit 2c28f68)
- Created `packages/llm_tracker_plugin_keyword_block/` — TEST-ONLY plugin
  that returns `Block(...)` from `on_request_received` when the request
  body contains any keyword from `LLMTRACK_KEYWORDS_BLOCK_LIST`
  (case-insensitive, comma-separated, defaults to a built-in tiny list).
  Hook: `on_request_received` only. Capabilities:
  `read_request_content`, `block_request`. 8 unit tests in
  `tests/test_keyword_block.py`. Manifest signed by `minseop`. (commit
  2c28f68)
- Updated `pyproject.toml` (workspace root) `[tool.pytest.ini_options]
  testpaths` to include both new test directories. (commit 2c28f68)
- Refreshed `uv.lock` for the two new workspace members. (commit 2c28f68)

## Decisions

- **token_counter writes to its own sqlite file** (`var/plugin_token_counter.db`)
  rather than the core `Exchange.input_tokens` columns or a `plugin_token_counter__*`
  table inside the core DB. Reason: the core `Exchange` columns belong to
  the Phase-2 Extractor, and the host doesn't yet hand a session_factory to
  plugins via `HookContext`. A self-contained sidecar avoids both issues
  and is trivially removable. Acceptable because this plugin is explicitly
  test-only.
- **keyword_block keeps the forbidden list in code with an env override**
  (`LLMTRACK_KEYWORDS_BLOCK_LIST`, comma-separated) instead of reading from
  the core SQLite. Reason: zero coupling to the rest of the framework;
  exercise the block path with the smallest possible plugin.
- **Neither plugin declares `write_plugin_tables`.** That capability gates
  writes through the (not-yet-built) host-mediated DB API. token_counter
  uses an external file and keyword_block writes nothing, so declaring it
  would lie about the plugin's behavior.

## Verification

Full suite (existing 132 + new 18) green:

```
$ .venv/bin/python3.12 -m pytest -q
............ ... 150 passed in 0.98s
```

Targeted run for the two new packages:

```
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker_plugin_token_counter/tests \
    packages/llm_tracker_plugin_keyword_block/tests -q
..................                                                       [100%]
18 passed in 0.12s
```

Live plugin-loader smoke test (proves the bundled trust registry +
ed25519 signatures unblock both new manifests at runtime):

```
$ .venv/bin/python3.12 -c '...PluginHost.load_plugins()...'
loaded: ['hello_world', 'keyword_block', 'token_counter']
```

Lint / format clean on both packages:

```
$ .venv/bin/ruff format packages/llm_tracker_plugin_token_counter \
                          packages/llm_tracker_plugin_keyword_block
3 files reformatted, 5 files left unchanged
$ .venv/bin/ruff check  packages/llm_tracker_plugin_token_counter \
                          packages/llm_tracker_plugin_keyword_block
All checks passed!
```

## What's left / known limits

- Both plugins are explicit *throwaway test artefacts* and must be deleted
  before v1; track their removal in the Phase-2 Extractor / Phase-1c
  scope_guard worklogs respectively.
- token_counter's sidecar SQLite is plugin-local and not visible to
  `llm-tracker audit` — by design.
- token_counter parses Anthropic SSE only (the only adapter we ship).
  Other providers would no-op silently.

## Handoff

Both test plugins land in commit 2c28f68 and load cleanly. The user's
verification request for "what we've already built" is satisfied: the
response-chunk hook chain reaches usage data, the block path persists a
synthetic SSE response, and the bundled trust registry accepts a freshly
signed third-party plugin without core changes.

Next session can either:
1. Drive a real-traffic manual e2e against `https://api.anthropic.com`
   with both plugins loaded (start `llm-tracker start --mode L`, point
   `ANTHROPIC_BASE_URL` at the proxy, send a Claude Code request, then
   read both `var/llm_tracker.db` and `var/plugin_token_counter.db`); or
2. Open Phase 1c — `scope_guard` plugin — which is the canonical replacement
   for the `keyword_block` test plugin and the original "Next single
   step" before this detour. Worklog path:
   `docs/worklog/<YYYY-MM-DD>-phase1c-scope-guard.md`.

When Phase 1c starts, schedule the removal of `keyword_block` (subsumed
by `scope_guard`). `token_counter` stays until the Phase-2 Extractor
lands; track its removal in that phase's worklog.

## Suggestions (untouched)

- Once the host hands a session_factory through `HookContext` (Phase 1c+),
  re-evaluate whether sidecar-SQLite plugins are still the right shape or
  whether the canonical `plugin_<ns>__*` table pattern should subsume them.
