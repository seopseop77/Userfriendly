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

### Checkpoint 16 — Transform handling impl + tests (commit bbb33e7)

- `proxy/forwarder.py`: in the `before_forward` branch, after
  the existing Block check, add a Transform check that
  `headers.update(result.headers)` (plugin wins on conflict per
  ADR-0011 §1) and replaces `body` with `result.body` when not
  None (ADR-0011 §2). `PluginHost.before_forward` was already
  returning the first non-`Pass` result, so first-wins (ADR-0011
  §3) needed no host change.
- `tests/proxy/test_forwarder.py`: four new respx-driven tests
  exercise the policy end-to-end against a respx-mocked
  Anthropic upstream:
  - `test_transform_merges_new_header_into_request` — a `_Tagger`
    plugin adds `x-llm-tracker-task`; the captured upstream
    request shows both the new header and the original
    `x-api-key`.
  - `test_transform_plugin_header_wins_on_conflict` — a
    `_Rewriter` overrides `x-api-key`; upstream sees the
    plugin's value, not the client's.
  - `test_transform_replaces_whole_body_when_body_is_set` — a
    `_BodySwapper` returns a wholly different JSON body;
    upstream sees that body verbatim.
  - `test_transform_multi_plugin_first_wins` — a `_First` and a
    `_Second` plugin both want to add headers; only `_First`'s
    header reaches upstream and `_Second`'s `before_forward`
    method is never called (verified by an explicit counter).
  Each test uses a small `_build_request_scope()` helper plus an
  `_empty_factory()` async helper to avoid copy-paste; the four
  tests' assertion sites stay short and pinned.

### Checkpoint 15 — ADR-0011 Transform policy (commit cfbbb8e, docs only)

- New `docs/decisions/0011-transform-policy.md`. Three sub-decisions
  per Cowork's Gate 1 — picked the user-approved option for each.
  - **Header policy**: merge; plugin wins on conflict. Most plugin
    use cases (tracing, audit, task tagging) are additive;
    replace-all-headers would silently break upstream auth.
  - **Body policy**: replace whole body when `Transform.body is
    not None`. JSON-Patch / structured-diff would lock the SDK to
    one provider's body shape (Anthropic vs OpenAI vs Gemini
    differ); disallowing body changes would cripple PII-scrubbing
    plugins exactly when Mode A / Mode R operators need them.
  - **Multi-plugin policy**: first-wins. Consistent with Block
    first-wins; chaining produces fragile non-local interactions
    between plugins. Reversible later if a real chaining use case
    appears.

### Checkpoint 14 — ADR-0010 retroactive ratification (docs only)

- New `docs/decisions/0010-block-abort-plugin-field.md`
  retroactively documents the SDK change made in checkpoint 10
  (commit b1724fa): `Block` and `Abort` carry an optional
  `plugin: str = ""` field, set by the host so the forwarder
  can populate `exchanges.blocked_by`.
- ADR enumerates the three implementation routes considered
  (per-host transient state; tuple return; optional dataclass
  field) and explains why option 3 won (no concurrency hazard,
  no breaking change for plugin authors, no cascade through
  dispatcher signatures).
- No code or tests change. CLAUDE.md §10 is now satisfied for
  this contract extension.

### Checkpoint 13 — layering polish + ADR-0009 (commit 96305e1)

- `plugin_host/host.py`: new read-only `session_factory` property
  on `PluginHost` returning the underlying
  `async_sessionmaker[AsyncSession]`. Lets callers (currently the
  forwarder; later, plugin-side helpers) reach the factory
  without touching `_session_factory`.
- `proxy/forwarder.py`: both call sites that previously used
  `plugin_host._session_factory()` now use
  `plugin_host.session_factory()` (the timing-write block and
  the `_persist_block` helper). Layering fix only — no
  behaviour change.
- New ADR: `docs/decisions/0009-allowed-modes-required-non-empty.md`.
  Justifies tightening the manifest contract (option (a) per the
  user) over keeping the `list(VALID_MODES)` default or
  defaulting to `["L"]`. Security-first defaults are the core
  argument — silent enrolment of any plugin into Mode L violates
  ADR-0006's threat model.
- `llm_tracker_sdk/manifest.py`: `allowed_modes` is now
  `Field(..., min_length=1)` — required and non-empty. Existing
  `_validate_modes` validator continues to reject unknown mode
  strings; the new constraint just removes the silent default.
- `tests/test_manifest.py`: `_minimal()` now declares
  `allowed_modes`. New `test_missing_allowed_modes_rejected` and
  `test_empty_allowed_modes_rejected` pin the
  `ValidationError`s. (Side effect: ruff auto-fix on a now-stale
  import block also applied — harmless.)
- `hello_world` reference plugin: no manifest change needed
  (already declares `["L", "A", "R"]`); existing
  `plugin.toml.sig` stays valid; no re-signing.

### Checkpoint 12 — ADR-0008 housekeeping (docs only)

- `docs/decisions/0008-plugin-signing-trust-model.md`:
  - "Signing scope" now states the canonicalization rule
    (byte-exact `plugin.toml` contents) explicitly instead of
    listing it as a Phase 1b deferral.
  - "What is deferred" was renamed and split into "Resolved in
    Phase 1b" (canonicalization, signature storage format,
    signature blob format, registry file format, signing tooling,
    reference-plugin signing) and "What remains deferred"
    (boot-time verification cache, key rotation policy,
    revocation mechanism). Each resolved item points at the
    worklog checkpoint and commit hash that landed it.
  - "Open questions" pointer updated.

No code or tests change in this checkpoint.

### Checkpoint 11 — `audit_log` append-only DB triggers (commit 2891e8f)

- `storage/models.py`: replace the "deferred to Phase 1b" comment
  on `AuditLog` with a pointer to two new module-level DDL
  constants — `AUDIT_LOG_NO_UPDATE_DDL` and
  `AUDIT_LOG_NO_DELETE_DDL`. Each contains a `CREATE TRIGGER IF
  NOT EXISTS … BEFORE {UPDATE,DELETE} … RAISE(ABORT,
  'audit_log is append-only')` statement. SQLAlchemy
  `event.listen(AuditLog.__table__, "after_create", DDL(...))`
  attaches them so any code path that runs
  `Base.metadata.create_all` (production startup, all test
  fixtures) installs them automatically.
- New Alembic migration
  `alembic/versions/c2d3e4f5a6b7_audit_log_append_only_triggers.py`:
  imports the same DDL constants and `op.execute()`s them on
  upgrade. Downgrade drops both triggers. Single source of truth —
  the migration cannot drift from the listener-driven path.
- `tests/test_audit_triggers.py` (3 tests): `test_insert_succeeds`
  pins that audit writes still work. `test_update_raises` and
  `test_delete_raises` issue raw `UPDATE` / `DELETE` SQL through
  SQLAlchemy and assert `IntegrityError` matching `"append-only"`.
  Triggers fire at SQLite level, surfacing as `sqlite3.IntegrityError`
  via `aiosqlite` (not `OperationalError` — initial guess was
  wrong, corrected after the first run).

### Checkpoint 10 — synthetic SSE block response per ADR-0002 §3 (commit b1724fa)

- `forwarder.py`:
  - `_block_sse_chunks(reason, exchange_id)` emits the six-event
    Anthropic stream documented in ADR-0002 §3:
    `message_start → content_block_start → content_block_delta`
    (single `text_delta` carrying `"[llm-tracker] <reason>"`) `→
    content_block_stop → message_delta` (`stop_reason="end_turn"`,
    `usage.output_tokens=0`) `→ message_stop`. `tool_use` is never
    emitted.
  - `_block_response(reason, exchange_id)` returns a
    `StreamingResponse` at status **200** with
    `text/event-stream`, replacing the prior 503 plain-text path
    (the exact option ADR-0002 said NOT to use). Each call site
    that previously called `_block_response(result.reason)` now
    also calls `_persist_block(...)` to write the `Exchange` row.
- `storage/exchanges.py`: new `record_exchange_blocked` helper
  next to `record_exchange_timing`. Same defaults
  (`session_id="local"`, `provider="anthropic"`,
  `content_level="L0"`) plus the new `blocked_by` field. Sets
  `started_at` from the request-received timestamp passed in.
- `packages/llm_tracker_sdk/src/llm_tracker_sdk/hooks.py`: `Block`
  and `Abort` gain `plugin: str = ""` with a docstring noting it
  is host-set. Backward compatible — existing plugin code building
  `Block(reason="…")` keeps working unchanged.
- `plugin_host/host.py`: each dispatcher that may return Block /
  Abort now sets `result.plugin = plugin.name` before returning.
  Affects `on_request_received`, `before_forward` (Block branch),
  `on_upstream_response_start`, `on_response_chunk` (Abort
  branches). The Transform branch is untouched (Gate 1 still
  pending).
- `tests/proxy/test_forwarder.py`:
  - `_parse_sse_events(payload)` strict SSE parser used by the
    new test (asserts both `event:` and `data:` lines exist for
    every chunk).
  - `test_block_emits_synthetic_anthropic_sse` injects a
    `_Blocker` plugin into the host, drives `forward_request`
    directly with a constructed Starlette `Request`, parses the
    SSE bytes back, asserts the event order, the `[llm-tracker]
    out of scope` payload, `stop_reason=end_turn`, the absence of
    `tool_use` anywhere in the body, and the persisted
    `Exchange.blocked_by == "blocker"`.

### Checkpoint 9 — `on_persisted` ordering fix in forwarder (commit a2bc3d4)

- Modified `packages/llm_tracker/src/llm_tracker/proxy/forwarder.py`:
  hoisted `record_exchange_timing(...)` ahead of
  `plugin_host.on_persisted(...)`. design.md §6.3.2 says
  `on_persisted` runs *after* the local DB write so plugins can
  read the exchange row back; the prior order
  (`on_response_complete → on_persisted → record_exchange_timing`)
  left the row invisible to any plugin opening a session in the
  hook. Also collapsed the now-redundant nested
  `plugin_host is not None` check into one outer guard.

- Added `test_on_persisted_sees_exchange_row` in
  `packages/llm_tracker/tests/proxy/test_forwarder.py`:
  drives `forward_request` directly with a constructed Starlette
  `Request` + respx-mocked upstream (so it bypasses the FastAPI
  lifespan and doesn't depend on `Settings()` / a real database
  configuration). A `_ReaderPlugin` whose `on_persisted` opens a
  session and selects the exchange row asserts the row is
  non-empty after the body is drained.

### Checkpoint 8 — manifest signature verifier wired into the loader (commit 3010aae)

- Added `packages/llm_tracker/src/llm_tracker/trust/__init__.py` and
  `keys.toml`. `load_bundled_registry()` reads the TOML bytes via
  `importlib.resources` and delegates to `signing.load_registry()`.
  `keys.toml` ships with one entry: `name = "minseop"`,
  `public_key = "fea581bb716aa51fc0c68b32601479a9fa6a633753b9ffacd0ee561127c03ac2"`
  (generated by the user via the new CLI; private half stored in
  the OS keychain).

- Modified `packages/llm_tracker/src/llm_tracker/plugin_host/host.py`:
  - `PluginHost.__init__` now accepts an optional
    `registry: dict[str, VerifyKey] | None = None`. Default behaviour
    calls `load_bundled_registry()`. Tests pass an explicit registry
    (or, more commonly, monkeypatch the verifier — see `_bypass_verifier`)
    so the empty-registry-during-cleanup-pass period didn't block them.
  - New instance method `_verify_manifest(plugin_class)` resolves the
    plugin's top-level package via `importlib.resources.files`, reads
    `plugin.toml` byte-exact and the sibling `plugin.toml.sig` (or
    `None` if absent), and calls `verify_manifest_signature` against
    `self._registry`. Returns `(VerifyResult, signer)`.
  - In `load_plugins()`, the verifier runs between `_find_manifest()`
    and `denied_capabilities()`. On any non-`VERIFIED` outcome the
    host writes a `manifest_rejected` audit row whose `detail_json`
    carries `{"reason": <verify_result.value>}` plus `"signer": <name>`
    when the verifier returned one (`VERIFIED` and
    `SIGNING_KEY_NOT_IN_REGISTRY` cases) and skips the plugin.

- Modified `packages/llm_tracker/src/llm_tracker/cli/main.py`:
  - `llm-tracker generate-key <name>` — generates an ed25519 keypair,
    stores the private half in the OS keychain via `keyring`
    (service `"llm-tracker-signing"`, account = signer name), prints
    the public hex with a paste-ready `[[key]]` block. Refuses to
    overwrite an existing keychain entry to avoid accidental rotation.
  - `llm-tracker sign-plugin <pkg-path> --signer <name>` — locates
    `plugin.toml` either at `<pkg-path>/plugin.toml` or under
    `<pkg-path>/src/*/plugin.toml`, reads its byte-exact content,
    signs with the keychain-stored private key, and writes a sibling
    `plugin.toml.sig` containing TOML `signer` + `signature` (hex).
  - Both commands use `Annotated[..., typer.Argument(...)]` for
    positional args to satisfy ruff B008 (typer's older
    `arg = typer.Argument(...)` shape triggers the rule).

- Added `packages/llm_tracker_plugin_hello_world/src/llm_tracker_plugin_hello_world/plugin.toml.sig`
  produced by `llm-tracker sign-plugin --signer minseop`. The bundled
  reference plugin now satisfies ADR-0008 hard-reject under the
  default registry.

- Updated `packages/llm_tracker/tests/test_plugin_host.py` (+3 tests
  + helper):
  - `_bypass_verifier(monkeypatch)` helper short-circuits
    `_verify_manifest` to `(VERIFIED, "test-signer")` for tests that
    monkeypatch fake plugins (which ship no `.sig`). Used by the four
    pre-existing load-plugins tests that target other paths
    (egress-guard wiring, capability policy).
  - `test_load_plugins_verifies_real_hello_world_signature` —
    integration test: real `HelloWorldPlugin` class, real
    `plugin.toml`, real `plugin.toml.sig`, real bundled registry. No
    bypass. Asserts the plugin loads, no `manifest_rejected`, and
    a `plugin_loaded` audit row is written with `outcome="ok"`.
  - `test_load_plugins_rejects_when_signature_missing` — unit test
    of the loader's reject path: `_verify_manifest` returns
    `SIGNATURE_MISSING`, loader writes `manifest_rejected` with
    `detail_json={"reason": "signature_missing"}` and skips the
    plugin.
  - `test_load_plugins_records_signer_when_key_not_in_registry` —
    pins that `SIGNING_KEY_NOT_IN_REGISTRY` surfaces the asserted
    signer in `detail_json` (regression guard for the ADR-0008
    distinction between this outcome and `signature_invalid`).

### Checkpoint 7 — EgressGuard wired into proxy lifespan (commit e2ee4f0)

- Modified `packages/llm_tracker/src/llm_tracker/proxy/app.py`:
  - In `lifespan()`, build `EgressGuard(mode=settings.mode,
    session_factory=factory)` alongside the host and pass it via
    `PluginHost(..., egress_guard=guard)`. Stash the guard on
    `app.state.egress_guard` so later phases (forwarder-side
    `egress.fetch`) can reach it without rebuilding it from settings.
  - `cli/main.py start` already boots the FastAPI app via uvicorn, so
    the lifespan change is the only wiring point — no CLI edits.

- Added `test_load_plugins_populates_egress_manifests_and_audits_attempt`
  in `packages/llm_tracker/tests/test_plugin_host.py` (1 test):
  pins the boot-time wiring contract — after `load_plugins()` the
  fake manifest is in `EgressGuard._manifests` (identity check), and
  a subsequent `check()` writes an `egress_attempt` row with the
  expected `plugin`/`destination`/`outcome=ok`. Companion to
  checkpoint 3's existing `test_load_plugins_registers_manifest_with_egress_guard`,
  which only asserted the public `check() is True` outcome.

- Did NOT add a plugin-facing `ctx.egress.fetch` API. That blocks on
  Gate 2 (hook payload shape / SDK contract for plugins to ask the
  guard about a URL); landing it now would freeze the wrong shape.

### Checkpoint 6 — ed25519 manifest signature verifier (primitive) (commit 2659284)

- Added `packages/llm_tracker/src/llm_tracker/plugin_host/signing.py`:
  - `VerifyResult` `StrEnum` with the four outcomes ADR-0008 §"Hard
    reject on failure" enumerates: `verified`, `signature_missing`,
    `signature_invalid`, `signing_key_not_in_registry`.
  - `load_registry(toml_bytes) -> dict[str, VerifyKey]` parses a
    `keys.toml` payload shaped as `[[key]]` array entries with
    `name` and `public_key` (hex). Raises `ValueError` only for
    distribution-bug shaped inputs (malformed TOML, missing fields,
    bad pubkey hex). The registry ships *inside* the core package
    so a malformed file is a build error, not a runtime fallback.
  - `verify_manifest_signature(manifest_bytes, sig_blob, registry)
    -> tuple[VerifyResult, str | None]`: never raises on
    operator-controlled bytes — every malformed sig_blob path
    returns `SIGNATURE_INVALID`. Returns the signer name on
    `VERIFIED` / `SIGNING_KEY_NOT_IN_REGISTRY` so the caller can
    audit it.

- Added `packages/llm_tracker/tests/test_signing.py` (16 tests):
  - Verifier outcome tests with ephemeral keys: round-trip verified,
    `SIGNATURE_MISSING` on `None` blob, `SIGNATURE_INVALID` on
    tampered manifest and on corrupted-but-correct-length signature,
    `SIGNING_KEY_NOT_IN_REGISTRY` when the asserted signer is absent.
  - Parametrized "malformed sig blob" matrix covering bad TOML,
    missing `signer`/`signature` field, bad hex, wrong-length hex,
    and non-UTF-8 bytes — all map to `SIGNATURE_INVALID`.
  - Registry-parsing tests: round-trip + the three distribution-bug
    failure modes.

- **Did NOT** wire the verifier into `PluginHost.load_plugins()`. The
  next checkpoint covers host wiring, which forces the bundled
  `keys.toml` to land on disk and the `hello_world` reference plugin
  to be signed (otherwise existing tests that exercise the real
  entry-point path would fail — ADR-0008 has no warn-and-continue
  mode). Splitting keeps each checkpoint surgical, mirroring the
  content-level primitive split (checkpoint 4 → not-yet-integrated).

### Checkpoint 5 — Mode-by-mode capability policy at load time (commit eb7bd67)

- Added `packages/llm_tracker/src/llm_tracker/plugin_host/policy.py`:
  - `MODE_DENIED_CAPABILITIES: dict[str, frozenset[str]]` — the only
    documented mode-policy entry from design.md §8 today is
    Mode L denies `egress_http`; Modes A and R deny none. Modes A/R
    runtime restrictions on egress (single destination / allowlist)
    stay in EgressGuard, not in this load-time table.
  - `denied_capabilities(mode, declared) -> frozenset[str]` — returns
    the subset of declared capabilities denied under `mode`. Unknown
    mode raises `ValueError` (closed L/A/R enumeration; same
    convention as `content_levels.effective_ceiling`).

- Modified `packages/llm_tracker/src/llm_tracker/plugin_host/host.py`:
  - After manifest validation and before `egress_guard.register()`,
    the host calls `denied_capabilities(self.mode, manifest.capabilities)`.
    On non-empty result it writes a `capability_denied` audit row
    (`detail_json = {"mode", "denied"}`, sorted) and skips the
    plugin — the guard never sees a manifest that the policy
    rejected.

- Added `packages/llm_tracker/tests/test_policy.py` (8 tests):
  table-shape assertions, parametrized `(mode, capability)` matrix
  spanning all 30 combinations, multiple-declared-subset returns
  only the denied subset, empty-declared always allowed, unknown
  mode raises.

- Updated `packages/llm_tracker/tests/test_plugin_host.py` (+2 tests):
  `test_load_plugins_rejects_egress_http_in_mode_L` (full audit-row
  shape pinned, plus a check that the egress guard's `_manifests`
  dict was *not* touched) and
  `test_load_plugins_accepts_egress_http_in_mode_R` (same manifest
  loads cleanly, no `capability_denied` row written).

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

### Checkpoint 16

The substantive policy choices for Transform live in ADR-0011;
this section captures only the implementation-level calls made
while landing the impl + tests:

- **Implement Transform in the forwarder, not the dispatcher.**
  `PluginHost.before_forward` was already returning the first
  non-`Pass` result, so first-wins was already in place. Pushing
  header/body merging into the host would couple the host to the
  proxy's HTTP shape; the forwarder is the natural seam, mirroring
  how `Block` resolves into a synthetic SSE response there.
- **`headers.update(...)` for the merge.** Plain `dict.update`
  gives exactly the "plugin wins on conflict" semantic ADR-0011
  picked. No need for a custom merge helper.
- **`_build_request_scope()` and `_empty_factory()` test
  helpers.** Four tests share the same Starlette scope and
  in-memory engine setup; small helpers keep each test's assertion
  site short. Not promoted to fixtures because each test still
  owns its own per-request scope mutation in principle.

(Checkpoints 12–15 had no Decisions entries: 12 was ADR-0008
housekeeping, 13's rationale lives in ADR-0009, 14 in ADR-0010,
15 in ADR-0011. The substantive reasoning sits in those ADRs.)

### Checkpoint 11

- **Single source of truth in `storage/models.py`, not duplicated
  SQL in the migration**. The constants `AUDIT_LOG_NO_UPDATE_DDL`
  and `AUDIT_LOG_NO_DELETE_DDL` are defined alongside the model;
  the Alembic migration imports them. If we tweak the trigger
  message later (or add a new one), one edit covers both prod and
  test paths.
- **`event.listen("after_create", DDL(...))` for the test path**.
  Tests use `Base.metadata.create_all`, which doesn't run Alembic
  migrations. Without the listener, the triggers would only exist
  in production DBs and the test suite would silently *not* be
  exercising them. The listener guarantees parity.
- **`CREATE TRIGGER IF NOT EXISTS`**, not `CREATE TRIGGER`. Both
  paths (listener fires per `create_all`; migration runs once)
  end up issuing the statement; idempotency means a re-run never
  fails.
- **`SELECT RAISE(ABORT, '...')` body, not `RAISE`. SQLite's
  trigger language requires `RAISE` inside a `SELECT` — bare
  `RAISE(ABORT, ...)` parses as a function call without a
  context. Standard SQLite idiom.
- **`IntegrityError`, not `OperationalError`**. SQLite's
  `RAISE(ABORT, ...)` surfaces as `sqlite3.IntegrityError` via
  `aiosqlite`, which SQLAlchemy maps to its own `IntegrityError`.
  First test draft asserted on `OperationalError` and failed; the
  test fix took precedence over a code change because the trigger
  itself is correct.

### Checkpoint 10

- **`plugin: str = ""` field on `Block` and `Abort`, not a
  separate wrapper class**. The forwarder needs the blocking
  plugin's name to populate `exchanges.blocked_by`, but the
  current dispatcher returns `Block`/`Abort` directly. Options
  considered: (1) host-side per-host or per-exchange transient
  state — concurrency-fragile under multiple in-flight requests;
  (2) host returns a tuple `(plugin_name, Block)` — breaks every
  test that does `isinstance(result, Block)`; (3) add an optional
  field with default. Option 3 is purely additive on a dataclass:
  no existing call site changes, plugins ignore it (it gets
  overwritten by the host before the forwarder sees the result).
  CLAUDE.md §10 lists "meaning of return values" as a public
  interface; an additive optional field with default doesn't
  redefine any existing meaning, but flagging here for
  visibility — if the user prefers an ADR for this, the change is
  small enough to revert and re-land under one.
- **Status 200, not 4xx/5xx**. ADR-0002 §3 picked Option B
  (synthetic SSE 200) explicitly because Claude Code parses the
  response as a normal model turn and won't retry. The prior 503
  matched ADR-0002 Option A (the rejected one); this checkpoint
  flips to the chosen option.
- **`stop_reason="end_turn"`, not `stop_sequence`**. ADR-0002 §3
  is explicit. Together with `tool_use` being absent, this stops
  Claude Code from running a tool call against the synthetic
  message.
- **Use `exchange_id` as the SSE `message.id`**. Saves a separate
  ULID for the synthetic message; debugging the audit log later
  is easier when the exchange row id matches the `message_start`
  payload's id. The model field is set to a constant
  `"llm-tracker-block"` so anything that filters on real model
  names skips this turn.
- **Persist a separate `Exchange` row, even though no upstream
  call happened**. The `Exchange` table is the audit-of-record
  for what happened in each request slot; a blocked request that
  doesn't appear in `Exchange` is invisible to operators reading
  the audit. `record_exchange_blocked` writes the minimum NOT
  NULL columns plus `blocked_by` and `started_at`, leaving
  `t_upstream_first_byte_ms` etc. NULL (they don't apply).
- **Persist *before* returning the StreamingResponse, not inside
  the SSE generator**. The DB write must happen unconditionally,
  including if Claude Code disconnects mid-stream. Writing inside
  `gen()` would couple the audit row to the client actually
  draining the body.
- **Abort path also goes through `_block_response`**. Cowork's
  instruction targeted Block specifically, but Abort and Block
  share the response-shape problem (both used to return 503
  plain text). Treating them symmetrically — same SSE shape,
  same `_persist_block` audit — keeps the forwarder simpler and
  avoids a future "abort gives plain text" surprise.

### Checkpoint 9

- **Direct `forward_request` test, not the existing ASGITransport
  pattern**. The other forwarder tests go through `app` and
  exercise the lifespan-built host, which under the cleanup pass
  loads the real `hello_world` and uses the real settings DB.
  Driving `forward_request` directly with a constructed Starlette
  `Request` and an explicit `PluginHost` is the smallest setup that
  exercises the post-stream code path with a known plugin and a
  known in-memory database. Mirrors `tests/test_plugin_host.py`'s
  fixture style for the engine + factory + Base.metadata.create_all.
- **Collapsing the nested `plugin_host is not None` check** is a
  minor cleanup that became natural once both timing-write and
  `on_persisted` sit under the same outer guard. Without that
  collapse the new ordering would have re-introduced a stray
  un-guarded `await` if `plugin_host` were `None` in the timing
  branch — flat structure makes the invariant readable in one pass.
- **Drained the `body_iterator` explicitly in the test** so that
  the post-stream block (timing write + `on_persisted` dispatch)
  actually runs. `StreamingResponse` is lazy; just constructing it
  inside `forward_request` is not enough.
- **Did NOT add a separate audit-trail check**. `on_persisted`
  already audits via `_audit("on_persisted", ...)`; that audit
  row's mere existence doesn't pin the ordering — only a row read
  inside the hook does. One assertion is enough; the hook-invoked
  audit case is already covered by `test_hook_invocations_logged`.

### Checkpoint 8

ADR-0008's two remaining deferred sub-decisions land here.

- **Signature storage location: sibling `plugin.toml.sig`** (vs an
  embedded `[_signature]` section vs a separate `MANIFEST.sig`).
  ADR-0008 listed all three. Sibling wins because the verifier
  consumes raw bytes; the other two options re-introduce a TOML
  parse/round-trip into the canonicalisation surface. Sibling is
  also the layout the `sign-plugin` CLI generates by default —
  `plugin.toml.with_name("plugin.toml.sig")`.
- **Reference-plugin signing: signed by the developer running the
  cleanup pass**, not by a build-bot key. ADR-0008 explicitly leaves
  this open for Phase 1b to decide; introducing a build-bot key now
  would require a CI key-management story that is out of scope. The
  `hello_world` plugin is signed by `minseop`, and `keys.toml` ships
  that one entry. Adding a build-bot key later is a one-PR follow-up.
- **Audit kind reuse, not a new `signature_rejected` kind**. The
  prior session's worklog flagged a correction here; this checkpoint
  honours it — non-`VERIFIED` failures all write `manifest_rejected`
  with the verifier reason in `detail_json`. Same kind grouping as
  unparseable manifests; operators can grep `manifest_rejected` and
  the `reason` distinguishes the failure mode.
- **`_verify_manifest` is an instance method, not a static**. It
  closes over `self._registry`, and being an instance method makes
  monkeypatching cleaner in tests (no need for a `staticmethod`
  wrapper). Mirrors how `_find_manifest` is `@staticmethod` only
  because it needs no host state.
- **Optional `registry` parameter on `PluginHost.__init__`**. Tests
  that monkeypatch `_verify_manifest` don't need it, but allowing a
  caller to pass an explicit registry leaves room for an integration
  test that uses a fixture-built registry against a synthesised .sig.
  Default `None` keeps existing call sites untouched.
- **`Annotated[..., typer.Argument(...)]` for positional CLI args**.
  Ruff's B008 fires only on `typer.Argument` (not `typer.Option`),
  so the new commands use the modern Annotated form for arguments
  and the older `= typer.Option(...)` shape for options. Mixed style
  inside a single function but consistent with the rest of the file
  for `Option` and lint-clean for `Argument`. Switching the existing
  commands to Annotated would be a separate cleanup pass.
- **`_bypass_verifier(monkeypatch)` helper, not a `conftest.py`
  autouse fixture**. The four affected tests are explicit about
  needing the bypass; an autouse fixture would silently disable the
  verifier across the whole module, including the integration test
  that depends on the real verifier path.
- **Keychain `service = "llm-tracker-signing"`**, not the project
  name. Easier to reason about for ops: any keychain GUI shows a
  single grouping of "what does llm-tracker remember", and the
  signing key role is explicit.
- **`generate-key` refuses to overwrite an existing keychain entry**
  for the same signer name. Forcing the user to delete first turns
  an accidental re-run into an explicit decision; matters because
  the previous private key would otherwise vanish silently.

### Checkpoint 7

- **EgressGuard built per-process at lifespan, not per-request**: the
  guard's `_manifests` map is populated once when `load_plugins()`
  runs; rebuilding the guard per request would discard registrations
  and force re-registration. Same lifetime as `PluginHost`.
- **Stash on `app.state.egress_guard`, not only inside PluginHost**:
  later phases need the forwarder to call `guard.check()` for the
  upstream LLM call (design.md §7.3 — single audit stream) without
  reaching through `PluginHost._egress_guard`. Exposing it on
  `app.state` mirrors the existing `app.state.plugin_host` pattern.
  Read-only from there; nobody mutates it after lifespan startup.
- **No `ctx.egress.fetch` plugin API in this checkpoint**: that's
  the SDK-side surface plugins use to ask the guard about a URL, and
  it depends on Gate 2 (hook payload shape — whether `ctx` is added
  to hook signatures or surfaced via a separate context object).
  Landing the API now would freeze the wrong shape; deferred.
- **`cli/main.py` untouched**: `start` boots uvicorn against
  `llm_tracker.proxy.app:app`, so the lifespan change is the only
  wiring point. Adding a CLI-side construct-then-pass-in step would
  duplicate config parsing and silently bypass uvicorn's reload flow.

### Checkpoint 6

ADR-0008 §"What is deferred" left four implementation choices to
Phase 1b. This checkpoint locks the two needed for the verifier;
the other two (signing CLI, reference-plugin signing approach)
land with the host-wiring checkpoint.

- **Canonicalization rule: byte-exact contents of `plugin.toml`.**
  The alternative — TOML round-trip — couples verification to
  whichever serializer's whitespace/quote conventions we pick today,
  and breaks signatures the moment we upgrade or swap libraries.
  Byte-exact has the property that "what was signed" and "what is on
  disk" are literally the same bytes; trivially auditable.
- **Signature blob format: TOML with `signer` + `signature` fields.**
  Carrying the asserted signer name in the blob lets the verifier
  return distinct `SIGNING_KEY_NOT_IN_REGISTRY` and
  `SIGNATURE_INVALID` outcomes — both ADR-0008 lists as separate
  failure reasons. Raw 64-byte signature alone would collapse them.
- **Signature storage location: deferred to host-wiring checkpoint.**
  ADR-0008 lists three options (sibling `plugin.toml.sig`,
  `[_signature]` section, separate `MANIFEST.sig`); the verifier
  doesn't care which one — it takes raw bytes. Picking blocks on
  the host side that has to *find* the blob, not the verifier.
- **Never-raise contract on operator bytes.** `verify_manifest_signature`
  returns `SIGNATURE_INVALID` for every malformed blob path — bad
  TOML, missing field, bad hex, wrong-length hex, non-UTF-8.
  Raising would let a broken plugin file crash the loader before
  the audit trail records it; the whole point of the audit log is
  to capture *which plugin* was bad and *why*.
- **`load_registry` *does* raise.** The registry ships inside the
  core package; a malformed file is a build/distribution bug, not
  a runtime condition. Same reasoning as
  `content_levels.effective_ceiling` raising on unknown mode.
- **`StrEnum` for `VerifyResult`.** The reason strings end up in
  audit-log `detail_json`; `StrEnum` lets the wiring code pass
  `result.value` (or rely on `str(result)`) without a separate
  serializer. Same shape as design.md §7.4's open kind/reason
  vocabulary.

### Checkpoint 5

- **Load-time enforcement, not hook-dispatch enforcement**: design.md
  §8 phrases the policy in terms of what each mode "permits". The
  cheapest faithful enforcement is to refuse the plugin at load time
  if it declares anything denied; per-hook checks would be redundant
  and noisier in the audit log. EgressGuard already enforces the
  *runtime* shape of `egress_http` (allowlist + Mode A's single
  destination), so this layer only needs to police *declarations*.
- **Single denial table, not per-capability mode lists**: today only
  one entry exists. Both shapes are equivalent for one entry; the
  current shape grows naturally if design.md later restricts more
  capabilities (just add to the per-mode set).
- **`capability_denied` audit kind**: matches the existing
  `manifest_rejected` / `egress_blocked` naming pattern. Not listed
  in design.md §7.4's example kind list, but §7.4 explicitly says
  the kind column is open ("plugin_loaded | hook_invoked | … |
  manifest_rejected"); a new denial reason fits the same
  audit-trail discipline.
- **Existing test `test_load_plugins_registers_manifest_with_egress_guard`
  uses Mode R**: I deliberately did not change it — that fixture's
  manifest declares `egress_http` and `allowed_modes=["L","A","R"]`,
  which under Mode L would now be rejected by the new policy. Mode R
  is still permissive, so the test continues to pin the
  egress-guard wiring as before.

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

### After checkpoint 16

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
........................................................................ [ 61%]
..............................................                           [100%]
118 passed in 0.81s

$ .venv/bin/ruff check \
    packages/llm_tracker/src/llm_tracker/proxy/forwarder.py \
    packages/llm_tracker/tests/proxy/test_forwarder.py
All checks passed!
```

(Checkpoint 15 was docs-only — ADR-0011; no test run needed.)

### After checkpoint 13

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
........................................................................ [ 63%]
..........................................                               [100%]
114 passed in 0.71s

$ .venv/bin/ruff check \
    packages/llm_tracker_sdk/src/llm_tracker_sdk/manifest.py \
    packages/llm_tracker/src/llm_tracker/plugin_host/host.py \
    packages/llm_tracker/src/llm_tracker/proxy/forwarder.py \
    packages/llm_tracker/tests/test_manifest.py
All checks passed!
```

### After checkpoint 11

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
........................................................................ [ 64%]
........................................                                 [100%]
112 passed in 0.72s

$ .venv/bin/ruff check \
    packages/llm_tracker/src/llm_tracker/storage/models.py \
    packages/llm_tracker/alembic/versions/c2d3e4f5a6b7_audit_log_append_only_triggers.py \
    packages/llm_tracker/tests/test_audit_triggers.py
All checks passed!
```

### After checkpoint 10

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
........................................................................ [ 66%]
.....................................                                    [100%]
109 passed in 0.68s

$ .venv/bin/ruff check \
    packages/llm_tracker/src/llm_tracker/proxy/forwarder.py \
    packages/llm_tracker/src/llm_tracker/storage/exchanges.py \
    packages/llm_tracker/src/llm_tracker/plugin_host/host.py \
    packages/llm_tracker_sdk/src/llm_tracker_sdk/hooks.py \
    packages/llm_tracker/tests/proxy/test_forwarder.py
All checks passed!
```

### After checkpoint 9

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
........................................................................ [ 66%]
....................................                                     [100%]
108 passed in 0.70s

$ .venv/bin/ruff check \
    packages/llm_tracker/src/llm_tracker/proxy/forwarder.py \
    packages/llm_tracker/tests/proxy/test_forwarder.py
All checks passed!
```

Side effect: ruff's auto-fix on `tests/proxy/test_forwarder.py`
incidentally cleaned up the pre-existing import-sort issue from
the Suggestions list (the new imports made the block messy enough
that `ruff check --fix` emitted a one-shot reorder which closed
the original I001 too). One down from the five pre-existing items.

### After checkpoint 8

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
........................................................................ [ 67%]
...................................                                      [100%]
107 passed in 0.69s

$ .venv/bin/ruff check \
    packages/llm_tracker/src/llm_tracker/cli/main.py \
    packages/llm_tracker/src/llm_tracker/plugin_host/host.py \
    packages/llm_tracker/src/llm_tracker/trust/__init__.py \
    packages/llm_tracker/tests/test_plugin_host.py
All checks passed!
```

(Repository-wide `ruff check` still reports the same pre-existing
errors carried in the Suggestions section: I001 in
`cli/main.py:17` inside the `init()` function-local imports, plus
the four others in `tests/proxy/test_forwarder.py` and
`tests/perf/report_first_token_latency.py`. Cleanup pass scope.)

End-to-end smoke check before committing:

```
$ .venv/bin/python3.12 -c "
from importlib.resources import files
from llm_tracker.trust import load_bundled_registry
from llm_tracker.plugin_host.signing import verify_manifest_signature
registry = load_bundled_registry()
pkg = files('llm_tracker_plugin_hello_world')
manifest = (pkg / 'plugin.toml').read_bytes()
sig = (pkg / 'plugin.toml.sig').read_bytes()
print(verify_manifest_signature(manifest, sig, registry))
"
(<VerifyResult.VERIFIED: 'verified'>, 'minseop')
```

### After checkpoint 7

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
........................................................................ [ 69%]
................................                                         [100%]
104 passed in 0.69s

$ .venv/bin/ruff check \
    packages/llm_tracker/src/llm_tracker/proxy/app.py \
    packages/llm_tracker/tests/test_plugin_host.py
All checks passed!
```

### After checkpoint 6

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
........................................................................ [ 69%]
...............................                                          [100%]
103 passed in 0.62s

$ .venv/bin/ruff check \
    packages/llm_tracker/src/llm_tracker/plugin_host/signing.py \
    packages/llm_tracker/tests/test_signing.py
All checks passed!
```

### After checkpoint 5

```
$ .venv/bin/python3.12 -m pytest packages/llm_tracker/tests/ -q
........................................................................ [ 82%]
...............                                                          [100%]
87 passed in 0.65s

$ .venv/bin/ruff check \
    packages/llm_tracker/src/llm_tracker/plugin_host \
    packages/llm_tracker/tests/test_plugin_host.py \
    packages/llm_tracker/tests/test_policy.py
All checks passed!
```

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
- [x] Mode-by-mode capability policy enforcement (commit eb7bd67 —
      enforced at *load time*; design.md §8 only mode-gates
      `egress_http` today, so a hook-dispatch enforcement layer
      would be a no-op for every other capability and is deferred
      until the policy table grows).
- [x] Manifest signature verification: verifier primitive
      (commit 2659284) + host wiring + bundled `keys.toml` +
      hello_world signed under that key (commit 3010aae). ADR-0008's
      `llm-tracker sign-plugin` deliverable is implemented; the
      companion `llm-tracker generate-key` writes the keypair to the
      OS keychain.
- [x] Proxy boot wiring: `proxy/app.py` lifespan now constructs
      `EgressGuard(...)` and passes it into `PluginHost(...)`. The guard
      is also stashed on `app.state.egress_guard` for later forwarder use.
      `cli/main.py` boots uvicorn against `llm_tracker.proxy.app:app`,
      so the lifespan is the single wiring point. (commit e2ee4f0)

## Suggestions (observed, not acted on)

- `ruff check` over the whole tree surfaces 4 pre-existing errors
  (was 5 — `tests/proxy/test_forwarder.py`'s I001 was incidentally
  cleaned up in checkpoint 9 when ruff's auto-fix touched the file
  to integrate the new imports): unsorted imports in `cli/main.py`,
  an `f`-string without placeholders plus a 102-char line in
  `tests/perf/report_first_token_latency.py`, plus the fifth in the
  same file. Cheap one-shot cleanup, but out of scope per CLAUDE.md
  §9.

## Out-of-band updates (Cowork)

- 2026-05-05: ADR-0008 (plugin signing trust model) sealed by Cowork — commit
  d39c487. Per-developer ed25519 keys, bundled public-key registry, verify at
  install AND boot, hard reject on failure. Manifest signature verification
  can now be implemented in Phase 1b without additional design work.

## Handoff

Checkpoint 16 complete (commit bbb33e7). Gate 1 (Transform
handling) is now fully landed: ADR-0011 documents the policy
(checkpoint 15, commit cfbbb8e), the forwarder honours
`Transform` returns from `before_forward` per the policy, and
four respx-driven tests pin the four behaviours (header merge,
header conflict, body replacement, multi-plugin first-wins).

Phase 1b cleanup-pass progress: A–G closed; ADR-0010 (retroactive)
closed; ADR-0011 + Gate 1 implementation closed.

Closed-checkpoint roll-up:

- A: EgressGuard wired into proxy lifespan (e2ee4f0)
- B: signature verifier wired + signing CLI (3010aae)
- C: on_persisted ordering fix (a2bc3d4)
- D: synthetic SSE block response (b1724fa)
- E: audit_log append-only triggers (2891e8f)
- F: ADR-0008 housekeeping (6a08c9c)
- G: session_factory property + ADR-0009 (96305e1)
- 14: ADR-0010 retroactive (654fbfb)
- 15: ADR-0011 Transform policy (cfbbb8e)
- 16: Transform impl + tests (bbb33e7)

Remaining: **Gate 2 — Hook payload routing (ADR-0012, option (b)).**
Add `HookContext` to the SDK; every hook signature gains
`ctx: HookContext`. `ctx` holds `session_id` + `exchange_id`
and exposes lazy accessors (`ctx.request_text(level=...)`)
that degrade per `effective_ceiling(mode, user_opted_in=...)`
at access time. `min_content_level` manifest field stays
deferred to Phase 1c. Sequence: write ADR-0012 (commit),
define `HookContext`, update `BasePlugin` and `PluginHost`
hook signatures, update `hello_world` (it can ignore `ctx`),
add tests (ctx is passed correctly, lazy accessors return
degraded data per mode). Each passing test group is its own
checkpoint.

### Open architectural questions (still Cowork → ADR)

Carrying forward from checkpoints 4 and 6:

1. **Manifest field for `min_content_level`** (design.md §7.1 says
   plugins declare a minimum required level). Public-interface
   change — needs ADR.
2. **Typed request/response payload object** for the hook
   dispatcher to apply `content_levels.degrade()` to.

Until both are answered, content-level integration cannot land.

### Next single step

**Write ADR-0012 (Gate 2 — Hook payload routing).** Path
`docs/decisions/0012-hook-context.md`. Document the user's
choice of option (b) `HookContext`:

- Hooks gain one extra parameter `ctx: HookContext`.
- `ctx` holds `session_id` and `exchange_id`.
- Lazy accessors (e.g. `ctx.request_text(level=...)`) degrade
  data at access time based on
  `effective_ceiling(mode, user_opted_in=...)`. Already-built
  primitives (`content_levels.effective_ceiling`,
  `content_levels.degrade`) supply the math.
- `min_content_level` manifest field is deferred to Phase 1c.

Commit ADR with scope `docs`. After the ADR commits, define
`HookContext` in the SDK, add the `ctx` parameter to all 8
hooks on `BasePlugin` (and the matching `PluginHost`
dispatchers), update `hello_world` to accept (and ignore)
`ctx`, and write tests pinning ctx propagation and degradation.
Each passing test group is its own checkpoint.
