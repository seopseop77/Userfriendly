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

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
......................                                                    [100%]
22 passed in 0.48s

$ .venv/bin/ruff check packages/llm_tracker/src packages/llm_tracker/tests packages/llm_tracker_plugin_hello_world/src
All checks passed!
```

## What's left / known limits

Remaining Phase 1b items (per roadmap.md):
- [ ] EgressGuard: enforce plugin-level `egress_destinations` allowlist + mode
      policy (Mode L denies all plugin egress; Mode A allows one approved dest).
- [ ] Capability use audit-logged on every EgressGuard call.
- [ ] Content-level routing (L0–L3): core degrades data before handing to plugins.
- [ ] Mode-by-mode capability policy enforcement with tests.
- [ ] Manifest signature verification (now unblocked — see ADR-0008).

## Out-of-band updates (Cowork)

- 2026-05-05: ADR-0008 (plugin signing trust model) sealed by Cowork — commit
  d39c487. Per-developer ed25519 keys, bundled public-key registry, verify at
  install AND boot, hard reject on failure. Manifest signature verification
  can now be implemented in Phase 1b without additional design work.

## Handoff

Checkpoint 1 complete. ADR-0008 (signing trust model) sealed by Cowork in
commit d39c487, so signature verification is no longer blocked. Next:
EgressGuard plugin-level allowlist enforcement — update `guard.py` to
accept a manifest allowlist per plugin and check mode policy.
