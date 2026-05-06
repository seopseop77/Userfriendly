# 2026-05-05 · Phase 1b — Security boundary hardening

**Author**: Claude Code
**Session trigger**: Resume — Phase 1a closed, begin Phase 1b per STATUS.md
**Related docs**: `docs/design.md §6.3.4, §7`, ADR-0006, `docs/roadmap.md §1b`

## Interpretation

Phase 1b hardens the security boundary of the plugin host and egress layer.
STATUS.md identified two first tasks: (1) hook dispatch timeout + exception
isolation in PluginHost so a plugin crash never propagates into the core, and
(2) manifest validation at plugin load time so a plugin without a valid
`plugin.toml` is rejected before it touches any hook.

## What was done

### Checkpoint 2 — EgressGuard: per-plugin allowlist + mode policy (commit 5bafac1)

- Modified `packages/llm_tracker/src/llm_tracker/egress_guard/guard.py`:
  - Added `register(manifest)` so the host can attach a `PluginManifest`
    by plugin name; the guard looks it up on every `check()`.
  - Replaced the Phase-0 deny-everything stub with a six-step decision
    flow encoded in `_evaluate()` (Mode L deny → manifest registered →
    mode in `allowed_modes` → capability declared → exact URL match →
    Mode A single-destination invariant). Returns a short reason string
    on denial; `None` on allow.
  - Audit entry now records `mode` and the denial `reason` in
    `detail_json`, so operators can grep `egress_blocked` and tell
    *why* in one pass.

- Added `packages/llm_tracker/tests/test_egress_guard.py`:
  - One denial-path test per branch in `_evaluate()` plus two happy-path
    tests (Mode A single, Mode R multiple), `register()` overwrite, and
    an exact-match guard against four wildcard-style near-misses.
  - All 10 tests use the same in-memory SQLite + `async_sessionmaker`
    fixture pattern as `test_plugin_host.py`.

### Checkpoint 1 — PluginHost: exception isolation + manifest validation (commit 04aa85f)

- Modified `packages/llm_tracker/src/llm_tracker/plugin_host/host.py`:
  - Added `HOOK_TIMEOUT = 5.0` constant.
  - Added `_call()` helper: wraps every plugin hook in `asyncio.wait_for()`
    with a 5-second timeout. On timeout or any exception, audits a
    `plugin_fault` entry and returns the safe default for that hook type.
  - Added `_find_manifest()` static method: locates `plugin.toml` via
    `importlib.resources.files(pkg_name)`, parses and validates it via
    `PluginManifest`. Returns `(None, reason)` on failure.
  - Updated `load_plugins()`: validates manifest before instantiating; on
    failure writes a `manifest_rejected` audit entry and skips the plugin.
  - All 8 hook dispatch methods now use `_call()` instead of bare `await`.

- Fixed `packages/llm_tracker_plugin_hello_world/src/llm_tracker_plugin_hello_world/__init__.py`:
  - Was importing `BasePlugin` from non-existent `llm_tracker.plugin_host.base`.
  - Changed to `from llm_tracker_sdk import BasePlugin`.

- Created `packages/llm_tracker_plugin_hello_world/src/llm_tracker_plugin_hello_world/plugin.toml`:
  - Minimal valid manifest for the hello_world no-op plugin.

- Updated `packages/llm_tracker/tests/test_plugin_host.py`:
  - `test_crashing_plugin_does_not_propagate`: injects a raising plugin, calls
    `on_request_received`, asserts Pass returned and `plugin_fault` audited.
  - `test_timeout_plugin_does_not_propagate`: injects a forever-sleeping plugin,
    patches `HOOK_TIMEOUT` to 0.05 s, asserts Pass returned and fault audited.
  - `test_load_plugins_rejects_missing_manifest`: monkeypatches `entry_points`
    to return a plugin class in a package with no `plugin.toml`; asserts
    `manifest_rejected` is written and the plugin is not loaded.

## Decisions

### Checkpoint 2

- **`register(manifest)` not constructor injection**: the host loads
  plugins lazily via `entry_points`, so the guard cannot know its
  manifests at construction time. A `register()` call after each
  successful manifest validation matches the existing
  `PluginHost.load_plugins()` flow and keeps the guard's lifecycle
  decoupled from plugin discovery.
- **Single-destination invariant lives in EgressGuard, not in
  `PluginManifest`**: design.md §8 says the *operator* approves one
  destination in Mode A. The manifest may legitimately list several
  candidates; the *runtime guard* is what enforces the policy. Pushing
  it into manifest validation would break Mode R plugins that reuse
  the same manifest.
- **Reason strings are stable identifiers, not free-text**: tests assert
  on them, and operators will likely build dashboards keyed on the
  `reason` field of `egress_blocked` audit entries. Picked
  `snake_case` tokens (`mode_L_denies_egress`,
  `capability_not_declared:<cap>`, etc.) so they read like
  enum-ish constants.
- **Exact-match enforcement is asserted by test, not by a separate
  validator**: `manifest.egress_destinations` is already a `list[str]`,
  so wildcards or globs would simply fail to match real URLs. Adding a
  dedicated rejection path would be defensive code for an impossible
  state (per CLAUDE.md §2.2). The near-misses test pins this behavior
  in case someone later "improves" the matcher.

### Checkpoint 1

- **`HOOK_TIMEOUT = 5.0` seconds**: consistent with design.md §6.3.4 ("bounded
  by timeout"). Five seconds is generous for in-process plugins; will tighten
  after measuring real plugin latencies in Phase 1c.
- **Fault = return default, never skip remaining plugins**: one plugin's fault
  should not silence a later plugin's BLOCK/ABORT. Remaining plugins still run.
- **`_find_manifest` via `importlib.resources`**: cleanest way to locate
  package data files for both editable and regular installs on Python 3.11+.
  Avoids `ep.dist.files` which can be `None` for editable installs.
- **`manifest_rejected` kind in audit_log**: new kind string, consistent with
  design.md §7.4 schema comment that lists `manifest_rejected` as a valid kind.

## Verification

### After checkpoint 2

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
................................                                          [100%]
32 passed in 0.63s

$ .venv/bin/ruff check \
    packages/llm_tracker/src/llm_tracker/egress_guard/guard.py \
    packages/llm_tracker/tests/test_egress_guard.py
All checks passed!
```

(Repository-wide `ruff check` reports 5 pre-existing errors in
`cli/main.py`, `tests/perf/report_first_token_latency.py`, and
`tests/proxy/test_forwarder.py` — see Suggestions below.)

### After checkpoint 1

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
......................                                                    [100%]
22 passed in 0.48s

$ .venv/bin/ruff check packages/llm_tracker/src packages/llm_tracker/tests packages/llm_tracker_plugin_hello_world/src
All checks passed!
```

## What's left / known limits

Remaining Phase 1b items (per roadmap.md):
- [x] EgressGuard: enforce plugin-level `egress_destinations` allowlist + mode
      policy. (commit 5bafac1)
- [x] Capability use audit-logged on every EgressGuard call. (subsumed by 5bafac1
      — every check writes `egress_attempt`/`egress_blocked` with
      `capability`, `destination`, mode, and reason.)
- [ ] PluginHost wires loaded manifests into `EgressGuard.register()` (today
      `load_plugins()` validates a manifest but discards it; the guard cannot
      enforce until the host hands it over).
- [ ] Content-level routing (L0–L3): core degrades data before handing to plugins.
- [ ] Mode-by-mode capability policy enforcement at hook dispatch (currently
      only enforced inside the egress path).
- [ ] Manifest signature verification (now unblocked — see ADR-0008).

## Suggestions (observed, not acted on)

- `ruff check` over the whole tree surfaces 5 pre-existing errors:
  unsorted imports in `cli/main.py` and `tests/proxy/test_forwarder.py`,
  an `f`-string without placeholders plus a 102-char line in
  `tests/perf/report_first_token_latency.py`. Cheap one-shot cleanup,
  but out of scope for this checkpoint per CLAUDE.md §9.

## Out-of-band updates (Cowork)

- 2026-05-05: ADR-0008 (plugin signing trust model) sealed by Cowork — commit
  d39c487. Per-developer ed25519 keys, bundled public-key registry, verify at
  install AND boot, hard reject on failure. Manifest signature verification
  can now be implemented in Phase 1b without additional design work.

## Handoff

Checkpoint 2 complete (commit 5bafac1). EgressGuard now enforces the
manifest-driven allowlist with the mode policy from design.md §7.3 / §8.
The guard's API and contract are stable, but **nothing wires manifests
into it yet** — `PluginHost.load_plugins()` validates a manifest and
then discards it.

Next single step: thread the validated `PluginManifest` from
`PluginHost.load_plugins()` into a constructor-injected
`EgressGuard.register()` call. Concrete shape:

1. Give `PluginHost.__init__` an optional `egress_guard: EgressGuard | None`.
2. When `_find_manifest()` succeeds, also call
   `egress_guard.register(manifest)` before instantiating the plugin.
3. Add a `test_plugin_host.py` test that loads a real fixture plugin and
   asserts `EgressGuard.check(...)` for that plugin's declared
   destination returns `True` under Mode R.

Do this before content-level routing — the latter only matters once
plugins can actually call out, which requires the wiring above.
