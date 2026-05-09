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

## Decisions

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

## Verification

```
$ .venv/bin/python3.12 -m pytest \
    packages/llm_tracker/tests/proxy/test_exchange_context_lifecycle.py \
    packages/llm_tracker/tests/proxy/test_forwarder.py -q
............                                                             [100%]
12 passed in 0.41s

$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests -q
189 passed, 4 warnings in 6.56s

$ .venv/bin/python3.12 -m ruff format <changed files>
1 file reformatted, 1 file left unchanged

$ .venv/bin/python3.12 -m ruff check <changed files>
All checks passed!
```

The 4 warnings are pre-existing `cli/manage.py` `os.fork()` deprecation
notices, untouched by this checkpoint.

## What's left / known limits

- Checkpoint 2 (per-level shape of `HookContext.request_text` + new
  `request_hash()` / `request_length()` accessors) — still owed.
- Closing checkpoint (STATUS.md cleanup, worklog handoff, docs commit) —
  after CP2.

## Handoff

CP1 closed. Next single step: **start CP2** — refine
`HookContext.request_text(level=...)` so L1 returns `None`, add
`request_hash()` and `request_length()` derived from
`_raw_request_body`, document the per-level shape in
`docs/plugins.md`, and update the SDK tests to lock the contract.
The existing `test_hook_context.py::test_request_text_returns_body_when_within_ceiling`
expects raw text at L1 in Mode L; that test must be rewritten to
expect `None` for `request_text(L1)` and the populated hex/int from the
new accessors.

## Suggestions (untouched)

- None observed during CP1.
