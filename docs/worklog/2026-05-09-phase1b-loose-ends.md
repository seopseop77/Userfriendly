# 2026-05-09 · Phase 1b loose ends

**Author**: Claude Code
**Session trigger**: "Resume Phase 1b — close the loose ends so the phase
is unambiguously done. STATUS.md 'Phase 1b loose ends' lists two items
still owed before we declare victory."
**Related docs**: `docs/STATUS.md` ("Phase 1b loose ends"),
`docs/worklog/2026-05-05-phase1b-security.md`,
`docs/worklog/2026-05-07-supabase-sink.md`,
`docs/design.md §6.3, §7.1`, ADR-0006 (modes), ADR-0012 (HookContext)

## Interpretation

Two distinct refinements were on the deferred list at the end of Phase 1b
and remained deferred all the way through the supabase_sink workstream.
Both are small enough to land as standalone checkpoints, neither needs
its own ADR, and closing both lets STATUS.md's "Phase 1b loose ends"
section retire.

- **CP1** — `end_exchange` leak in the forwarder. `PluginHost`
  exposes `begin_exchange()` and `end_exchange()` but the forwarder only
  ever called `begin_exchange`. `_exchange_contexts` grew unboundedly
  across requests.
- **CP2** — `HookContext.request_text(level=...)` returns raw text at
  every level ≥ L1 today. Per design.md §7.1 L1 should be metadata + a
  hash of the body, not the body itself. The L2 scrubbed shape stays
  deferred (needs scrubber primitives), but the L1/L3 split is locally
  shippable.

After both checkpoints, STATUS.md's "Phase 1b loose ends" section is
removed; the items that legitimately need other Phase-1c work
(L2 scrubbed shape, manifest `min_content_level`, response-side
accessors) move under a new "Phase 1c prerequisites" heading so they're
no longer mis-labelled as Phase-1b debt.

## What was done

### Checkpoint 1 — `end_exchange` leak fix

- Modified `packages/llm_tracker/src/llm_tracker/proxy/forwarder.py` —
  `_block_response()` now takes the `PluginHost` and its inner async
  generator wraps the chunk loop in `try/finally:
  plugin_host.end_exchange(exchange_id)`. The main `generate()` gains
  an outer `try/finally` that runs `end_exchange` after the
  post-completion `record_exchange_timing` / `on_persisted` block.
  All three Block/Abort early-return call sites now pass `plugin_host`
  through to `_block_response`. (commit 86acecd)
- Created
  `packages/llm_tracker/tests/proxy/test_exchange_context_lifecycle.py`
  — three tests covering: normal completion drains
  `_exchange_contexts` empty; Block from `on_request_received` drains
  empty (synthetic SSE generator path); Abort from
  `on_upstream_response_start` drains empty (early-exit after upstream
  open). (commit 86acecd)

### Checkpoint 2 — `request_text` per-level shape

- Modified `packages/llm_tracker_sdk/src/llm_tracker_sdk/hook_context.py`
  — `request_text(level)` now returns `None` for any effective level
  ≤ L1; raw decoded text only at L2 / L3. Two new accessors:
  `request_hash()` (hex SHA-256 of `_raw_request_body`,
  `effective_ceiling() >= L1`) and `request_length()` (byte length,
  same gate). `import hashlib` is stdlib — no new dependencies.
  Module docstring carries the per-level shape table; the L2-as-raw
  decision is documented as deferred to Phase 1c. (commit 86caf03)
- Modified `packages/llm_tracker/tests/test_hook_context.py` —
  rewritten to lock the new contract end-to-end. Three groups of
  tests: `effective_ceiling` (unchanged), `request_text` per-level
  shape (L0/L1 → None at every mode; L2/L3 → text at high ceilings;
  invalid UTF-8 → None at L3), and the new `request_hash` /
  `request_length` accessors (both `None` at L0; both populated at
  L1 and L3; SHA-256 over raw bytes works on non-UTF-8).
  (commit 86caf03)
- Modified `packages/llm_tracker/tests/test_plugin_host.py` —
  `test_begin_exchange_passes_ctx_to_each_hook` updated: Mode L now
  expects `request_text(L1) is None` plus `request_hash()` / `request_length()`
  populated (the L1 escape hatch). (commit 86caf03)
- Modified `packages/llm_tracker_plugin_keyword_block/tests/test_keyword_block.py`
  — `_ctx()` helper defaults to `mode="R", user_opted_in=True`. The
  plugin needs raw text to function; pre-Phase-1c only Mode R + opt-in
  exposes it. The `test_passes_when_body_unavailable` test still
  pins the "no signal → pass" branch. The plugin code itself
  is untouched. (commit 86caf03)
- Modified `docs/plugins.md` — new §3.1 "What `HookContext` exposes
  per level" with the per-level shape table and reading rules of
  thumb. Cross-references design.md §7.1 and the test-only
  `keyword_block` plugin as the canonical "treat None as no signal"
  example. (commit 86caf03)

## Decisions

### CP1

- **Cleanup belongs in the generators that `StreamingResponse`
  iterates, NOT in `forward_request`'s function body**. `forward_request`
  returns to Starlette before any of `gen()` / `generate()` runs, so a
  cleanup in the function body would always fire too early on the
  successful return path. Reasoned through this in the planning step
  with the user; comment in `_block_response` and `generate()` records
  the *why*.
- **Lean on `end_exchange`'s existing idempotency** (`dict.pop(...,
  None)`). The outer try/finally on `generate()` runs after the
  inner try/finally already drained — calling it twice in any
  pathological future refactor is a no-op, not a crash. Keeps the
  fix minimal.
- **Pass `plugin_host` into `_block_response` rather than splitting
  the helper**. The alternative (a separate `_block_response_with_cleanup`
  wrapper) inflates the call sites without gain. The signature change is
  internal — `_block_response` has no external callers (verified via
  `grep`).
- **No ADR**. ADR-0012 already specifies the lifecycle contract; this is
  a defect-class fix that aligns the implementation with the contract.

### CP2

- **L2 still returns raw text today; do NOT bolt on a placeholder
  scrubber**. design.md §7.1's L2 promise is "scrubbed body
  (secrets/PII/paths/emails/IPs removed)"; that requires real
  scrubber primitives (Phase 1c). A stub that pretends to scrub
  while letting raw bytes through would be worse than admitting
  the deferral. The SDK docstring + `docs/plugins.md` §3.1 + this
  worklog all flag the temporary equivalence between L2 and L3.
  Tracked under STATUS "Phase 1c prerequisites" after the closing
  checkpoint.
- **Hash + length share the same L1 gate**. Both accessors
  return `None` whenever `effective_ceiling() < L1` and a
  non-`None` value whenever `>= L1`. design.md §7.1 lists
  hashes and lengths together at L1, so a split gate would
  drift from the spec. The unified gate also keeps the SDK
  surface compact (one rule to remember: "L1 escape hatch").
- **Update test fixtures, not plugin code, for `keyword_block`**.
  Per CLAUDE.md §2.3, the plugin's runtime behavior was already
  correct ("treat `None` as no signal, pass through"); the fixture
  was Mode L because the previous SDK contract leaked raw text
  there. Switching the fixture to Mode R + opt-in is the smaller
  surgical change.
- **No ADR**. CP2 is a refinement of ADR-0012's contract,
  documented in the SDK docstring + `docs/plugins.md` §3.1 +
  cross-reference to design.md §7.1. Same reasoning ADR-0012
  itself used when deferring `min_content_level` to Phase 1c.

## Verification

### CP1

```
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker/tests/proxy/test_exchange_context_lifecycle.py \
    packages/llm_tracker/tests/proxy/test_forwarder.py -q
............                                                             [100%]
12 passed in 0.41s

$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests -q
189 passed, 4 warnings in 6.56s
```

### CP2

```
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker/tests/test_hook_context.py \
    packages/llm_tracker/tests/test_plugin_host.py \
    packages/llm_tracker_plugin_keyword_block/tests/ -q
.................................................                        [100%]
49 passed in 5.64s

$ .venv/bin/python3.12 -m pytest packages -q
267 passed, 4 warnings in 7.08s

$ .venv/bin/python3.12 -m ruff format <CP2 changed files>
4 files left unchanged

$ .venv/bin/python3.12 -m ruff check <CP2 changed files>
All checks passed!
```

The 4 warnings are pre-existing `cli/manage.py` `os.fork()` deprecation
notices, untouched by this checkpoint.

## What's left / known limits

Nothing left in this workstream. The three items below are Phase-1c
prerequisites, not Phase-1b debt — they live under STATUS.md
"Phase 1c prerequisites" now:

- **L2 = raw text today**. Will switch to scrubbed output when Phase 1c
  ships scrubber primitives. Pinned by
  `test_hook_context.py::test_request_text_returns_body_at_l2_when_ceiling_allows`
  so the eventual change is test-visible.
- Manifest `min_content_level` field — needs `scope_guard`. Separate
  ADR (refines ADR-0012).
- Response-side `ctx` accessors (`response_text`,
  `tool_call_inputs`) — needs the Phase-2 Extractor; separate ADR if
  the partial-vs-assembled semantics surface anything non-obvious.

## Handoff

**Phase-1b loose-ends workstream closed.** Five commits land the
two refinements + their docs:

- 86acecd — proxy: pair begin_exchange with end_exchange (CP1)
- 14b6f7a — docs: open Phase-1b loose-ends worklog; CP1 closed
- 86caf03 — sdk: per-level shape for HookContext request accessors (CP2)
- 8d4422b — docs: Phase-1b loose-ends CP2 closed
- This commit — docs: Phase-1b loose-ends workstream closed; 1c prerequisites migrated

STATUS.md "Phase 1b loose ends (still deferred)" subsection
removed; the three Phase-1c-blocked items moved to a new top-level
"Phase 1c prerequisites" heading; "Next single step" re-states the
choice between Phase 1c kickoff (recommended; scope_guard, with a
planning interview for TaskDefinition / judge sizing / eval-set
acceptance criteria) and Phase 2 follow-ons (per-task consent UX,
`llm_tracker_server` routes, `drift_metrics` contributor plugin).

Next session: read STATUS.md "Next single step" and pick a
direction.

## Suggestions (untouched)

- None observed during CP1, CP2, or the closing checkpoint.
