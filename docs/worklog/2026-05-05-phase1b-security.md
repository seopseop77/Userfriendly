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

### Checkpoint 4 — Content-level ladder + per-mode ceiling primitive (commit 8ca5973)

- Added `packages/llm_tracker/src/llm_tracker/content_levels/__init__.py`
  (docstring-only) and `levels.py`:
  - `ContentLevel(IntEnum)`: L0 < L1 < L2 < L3, mirroring design.md
    §7.1's four-level ladder.
  - `_DEFAULT_CEILING`: per-mode plugin-visible ceiling (L→L1, A→L0,
    R→L1) and `_OPT_IN_CEILING` (R lifts to L3 with per-task user
    consent; L and A unchanged because they have no consent path).
  - `effective_ceiling(mode, *, user_opted_in=False) -> ContentLevel`:
    table lookup; raises `ValueError` on unknown mode.
  - `degrade(level, ceiling) -> ContentLevel`: `min(level, ceiling)` —
    can only lower, never elevate.

- Added `packages/llm_tracker/tests/test_content_levels.py` (14 tests):
  ladder ordering, IntEnum values, default ceiling per mode,
  Mode-R-only opt-in elevation, opt-in is a no-op for L/A, unknown-mode
  rejection, parametrized `degrade()` cases, never-elevate guard.

- **Did NOT** touch the plugin manifest schema. The design (§7.1) calls
  for plugins to declare a `min_content_level`; that field would change
  a public interface (CLAUDE.md §10) and needs an ADR before code.
  This checkpoint stays a pure runtime primitive.

- **Did NOT** wire content levels into hook dispatch. The dispatcher
  needs a typed payload object to degrade, and the codebase doesn't
  yet model request/response payloads beyond raw bytes — that's its
  own design step.

### Checkpoint 3 — PluginHost ↔ EgressGuard wiring (commit f1a31cf)

- Modified `packages/llm_tracker/src/llm_tracker/plugin_host/host.py`:
  - `PluginHost.__init__` now accepts an optional
    `egress_guard: EgressGuard | None = None`. Default `None` keeps
    every existing call site (including 7 prior tests) source-compatible.
  - In `load_plugins()`, after `_find_manifest()` succeeds and before the
    plugin is instantiated, the host calls
    `self._egress_guard.register(manifest)` when a guard was supplied.
    Manifest-rejection path is unchanged — a plugin without a valid
    manifest is never registered with the guard.

- Updated `packages/llm_tracker/tests/test_plugin_host.py`:
  - `test_load_plugins_registers_manifest_with_egress_guard`: monkeypatches
    `entry_points` and `_find_manifest` to inject a plugin with an
    egress-allowing manifest, then asserts
    `EgressGuard.check(...)` returns `True` for the declared destination
    under Mode R.
  - `test_load_plugins_skips_egress_register_when_manifest_invalid`: uses
    the existing `_FakeEP` (no `plugin.toml` on disk), asserts the guard
    still denies — proving rejection short-circuits before
    `register()` is reached.

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

### Checkpoint 4

- **`IntEnum` over `Enum + total_ordering`**: the ladder is naturally
  numeric (0–3) and the implicit `int` comparison is the whole point
  — call sites read `min(level, ceiling)` instead of `level.value`
  bookkeeping. The "implicit int leak" objection doesn't apply for
  an internal type that never crosses a serialization boundary
  (the storage column is a `TEXT` "L0"/"L1"/etc. anyway, persisted
  separately).
- **Two tables, not "level_with_offset"**: I considered modeling
  opt-in as `default_ceiling + opt_in_delta`, but Mode L's opt-in
  delta is +0, A's is +0, and R's is +2 (not a stable rule). Two
  flat lookup tables read more honestly.
- **`ValueError` on unknown mode, not silent fallback**: modes are a
  closed L/A/R enumeration — a typo here is a programming error in
  the call site, not a runtime condition. Per CLAUDE.md §2.2 ("no
  error handling for impossible scenarios"), the alternative would
  be silently denying egress under a typo'd "Mode L" — exactly the
  failure mode that produces ghost bugs.
- **Pointer correction**: STATUS.md said "design.md §7.5"; the
  content-levels section is actually §7.1. The §7.5 typo originated
  in checkpoint 3's "Next single step". Fixed in this checkpoint's
  STATUS update.
- **Manifest extension deferred to ADR**: design.md §7.1 says
  plugins declare a min level in the manifest. CLAUDE.md §10 lists
  the manifest schema as a public-interface contract requiring an
  ADR. Out of scope for this checkpoint; flagged in Handoff.

### Checkpoint 3

- **Optional `egress_guard` parameter, not required**: existing tests
  construct `PluginHost` without a guard; the proxy boot path will
  always supply one. Keeping it `Optional` matches Phase 0 callers and
  avoids a breaking signature change for fixture-only setups (CLAUDE.md
  §10 lists `__init__` shape implicitly under "public interfaces").
- **Register *before* instantiation**: the host calls `register()`
  before `plugin_class()`, so even if the plugin's `__init__` blocks
  or crashes, its egress allowlist is already enforceable. Putting it
  after instantiation would create a window where a misbehaving
  constructor leaks an unregistered plugin into the host while its
  manifest sits unused.
- **No audit entry for the register() call itself**: the `plugin_loaded`
  audit row already tells operators the manifest was accepted; the
  guard's per-`check()` audit covers actual egress decisions.
  Adding a third entry would be noise without information gain.

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

### After checkpoint 4

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
................................................                         [100%]
48 passed in 0.61s

$ .venv/bin/ruff check \
    packages/llm_tracker/src/llm_tracker/content_levels \
    packages/llm_tracker/tests/test_content_levels.py
All checks passed!
```

### After checkpoint 3

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
..................................                                       [100%]
34 passed in 0.59s

$ .venv/bin/ruff check \
    packages/llm_tracker/src/llm_tracker/plugin_host/host.py \
    packages/llm_tracker/tests/test_plugin_host.py
All checks passed!
```

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
- [x] PluginHost wires loaded manifests into `EgressGuard.register()`.
      (commit f1a31cf)
- [~] Content-level routing (L0–L3): primitive landed (commit 8ca5973).
      Three sub-pieces still open:
      - [ ] ADR + manifest extension for `min_content_level` (CLAUDE.md
            §10 — public interface).
      - [ ] Typed payload object that the dispatcher can degrade (today
            the host hands `exchange_id` + raw bytes around).
      - [ ] Wire `effective_ceiling()` + `degrade()` into hook dispatch
            so each plugin sees data only at its allowed level.
- [ ] Mode-by-mode capability policy enforcement at hook dispatch (currently
      only enforced inside the egress path).
- [ ] Manifest signature verification (now unblocked — see ADR-0008).
- [ ] Proxy boot wiring: `cli/main.py` (or wherever the host is constructed
      in the eventual Phase 1c boot path) must pass the EgressGuard into
      `PluginHost(...)`. The plumbing exists; nothing currently constructs
      both objects together.

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

Checkpoint 4 complete (commit 8ca5973). Content-level routing has its
primitive: `ContentLevel` IntEnum, per-mode default + opt-in ceilings
from design.md §7.1 / §8, `effective_ceiling()` and `degrade()`. No
caller consumes it yet — the integration step needs two prerequisites
that cross CLAUDE.md §10 / §4 (architectural decisions for Cowork):

### Open architectural questions (Cowork → ADR)

1. **Manifest field for `min_content_level`** (design.md §7.1 says
   plugins declare a minimum required level). Adding a key to
   `plugin.toml` changes a public interface — needs an ADR.
2. **Typed request/response payload object** for the hook dispatcher
   to degrade. Today `PluginHost` hands `exchange_id` + raw bytes;
   there is no structured object to apply `degrade()` to.

Until those are answered, content-level integration into hook
dispatch cannot land.

### Next single step (Claude Code, no ADR needed)

**Mode-by-mode capability policy enforcement at hook dispatch.** The
roadmap line is open; the policy is defined in design.md §6.3.3
(capability vocabulary) and §8 (mode-by-mode permissions). EgressGuard
already enforces this for `egress_http`; this checkpoint extends the
same pattern to the remaining capabilities so a Mode-L plugin cannot
exercise, say, `modify_request` if the operator has not approved it
in the current mode.

Concrete shape:

1. Add a `(mode, capability) -> allowed` lookup (likely
   `llm_tracker.plugin_host.policy`) sourced from design.md §8.
2. At plugin load time (right after manifest validation), reject any
   plugin whose declared capabilities are denied under the active
   mode — write `capability_denied` and skip the plugin.
3. Tests: per-(mode, capability) parametrized matrix + a load-time
   end-to-end test that a manifest with a denied capability is
   rejected and audited, while a permitted manifest loads.

Defer manifest signature verification (independent, also still on
the Phase 1b checklist; unblocked by ADR-0008) and the proxy-boot
wiring (Phase 1c) until after this.
