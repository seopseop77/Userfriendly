# 2026-05-11 · ADR-0021 signing-module removal

**Author**: Claude Code
**Session trigger**: User-driven housekeeping checkpoint queued by the
prior Phase-3a documentation session: "remove signing module and all
related artifacts (ADR-0021)". User explicitly bounded scope to the
removal list and held off Phase-3c kick-off.
**Related docs**: ADR-0021, ADR-0008 (superseded), ADR-0017,
`docs/STATUS.md`, prior worklog
`docs/worklog/2026-05-11-phase-3a-decisions.md`

## Interpretation

ADR-0021 retired the manifest-signing primitive at the documentation
level on 2026-05-11. This checkpoint is the matching code-removal pass
— delete-only, no behavior added. The task spec enumerated seven
removal targets (CLI commands, signing module, key registry,
PluginHost verification step, `.sig` files, SDK signing exports,
signing tests) and one explicit "Do NOT remove anything beyond this
list" constraint.

Two clarifications the spec implied but did not state outright:

- The "signing module" path in the spec
  (`packages/llm_tracker/src/llm_tracker/signing/`) does not exist as
  written. The actual artefacts are
  `packages/llm_tracker/src/llm_tracker/plugin_host/signing.py` (the
  verifier) and `packages/llm_tracker/src/llm_tracker/trust/` (the
  bundled key registry loader + `keys.toml`). Interpreted both as
  in-scope under "Signing module / key registry".
- The SDK has no signing exports today; `llm_tracker_sdk/__init__.py`
  ships the egress + hook + manifest surface only. The "SDK signing
  exports" bullet was a no-op for this checkpoint.

## What was done

(Single commit `b446c3f`; 14 files changed, 9 insertions, 616 deletions.)

- Deleted `packages/llm_tracker/src/llm_tracker/plugin_host/signing.py`
  — ed25519 verifier + `VerifyResult` enum + registry loader.
- Deleted `packages/llm_tracker/src/llm_tracker/trust/` directory —
  `keys.toml` (operator's public key) and `__init__.py`
  (`load_bundled_registry`).
- Edited `packages/llm_tracker/src/llm_tracker/cli/main.py` — removed
  `generate-key` and `sign-plugin` Typer commands, the
  `KEYRING_SERVICE` constant, the `from typing import Annotated`
  import that became unused. Module docstring updated to drop the
  retired commands.
- Edited `packages/llm_tracker/src/llm_tracker/plugin_host/host.py` —
  removed the `nacl`/`trust`/`.signing` imports, the `registry` ctor
  param + `_registry` attribute, the `_verify_manifest` method, and
  the verifier call site in `load_plugins`. ADR-0013 disable-by-config
  branch comment trimmed to no longer reference the verifier order.
- Deleted four `.sig` files:
  `llm_tracker_plugin_hello_world/.../plugin.toml.sig`,
  `llm_tracker_plugin_keyword_block/.../plugin.toml.sig`,
  `llm_tracker_plugin_supabase_sink/.../plugin.toml.sig`,
  `llm_tracker_plugin_token_counter/.../plugin.toml.sig`.
- Edited `packages/llm_tracker/pyproject.toml` — removed `keyring` and
  `pynacl` runtime deps (no other consumer in the core package).
- Deleted `packages/llm_tracker/tests/test_signing.py` — 11
  verifier-only unit tests.
- Edited `packages/llm_tracker/tests/test_plugin_host.py` — dropped
  the `_bypass_verifier` helper, the `VerifyResult` import, three
  signature-pinning tests
  (`test_load_plugins_verifies_real_hello_world_signature`,
  `..._rejects_when_signature_missing`,
  `..._records_signer_when_key_not_in_registry`), and the verifier-
  order assertion in `test_load_plugins_skips_disabled_by_config`.
  Twelve `_bypass_verifier(monkeypatch)` call sites in tests that
  exercised non-signing paths (manifest validation, mode policy,
  guard wiring, introspection) were removed; those tests now pass
  unconditionally because the verifier no longer exists.
- Edited `packages/llm_tracker_plugin_supabase_sink/tests/test_e2e.py`
  — dropped the `_verify_manifest` monkeypatch in
  `_wire_supabase_sink_only` and the `VerifyResult` import. Three e2e
  tests (happy / blocked / Mode L safety) untouched in behavior.
- Edited `docs/plugins.md` §10 — replaced the "Manifest signature
  verification, code review, and explicit capability approval"
  sentence with one that cites the new trust root (deploy pipeline)
  and references ADR-0021. No other docs touched (`design.md` and
  `roadmap.md` still describe the local-sidecar architecture; their
  rewrite is owed once Phase 3c is underway, see Suggestions).

## Decisions

- **Kept `pynacl` in `packages/llm_tracker_server/pyproject.toml`.**
  The server's `pynacl` dep was added for ADR-0007's planned
  TaskDefinition-signing flow, *not* for ADR-0008's plugin manifests.
  ADR-0017 superseded ADR-0007's deployment posture, but ADR-0021's
  scope is specifically "plugin manifest signing." The server's
  `pynacl` line is therefore not "made unused by these changes" in
  the CLAUDE.md §2.3 sense — it was never used. Removing it was
  outside the task spec's "Do NOT remove anything beyond this list"
  fence. Flagged as Suggestion #1 below for a follow-up clean-up if
  the team confirms the server will not bring its own crypto.
- **Dropped `keyring` + `pynacl` from `llm_tracker/pyproject.toml`
  without further checks.** Verified by grep that the only consumers
  were `cli/main.py`, `plugin_host/signing.py`, `plugin_host/host.py`,
  `trust/__init__.py`, `test_signing.py`, and `test_plugin_host.py`
  — all of which this commit removes or trims. No CLAUDE.md §10
  public interface other than the two retired CLI commands depended
  on either library.
- **Cleaned `_bypass_verifier` call sites instead of leaving them as
  no-ops.** The helper no longer existed after the import was removed;
  keeping dead call sites would fail at collection time. Removed each
  site individually so tests now make no claim about the verifier's
  existence.
- **Did not add a "smoke test that confirms plugin loading still
  works without signing"** even though STATUS.md §"Next single step"
  listed it. Rationale: the existing test_plugin_host.py suite
  (`test_load_plugins_registers_manifest_with_egress_guard`,
  `..._populates_egress_manifests_and_audits_attempt`,
  `..._accepts_egress_http_in_mode_R`, `..._skips_disabled_by_config`,
  `..._disabled_match_is_manifest_name_not_ep_name`, the introspection
  tests) and the supabase_sink e2e suite already pin the no-signing
  load path end-to-end. A new "smoke test" would be a duplicate.
  STATUS.md §"Next single step" was a recommendation, not a contract.
- **No `design.md` or `roadmap.md` edits.** The user's task list did
  not include them; CLAUDE.md §3 ("Surgical changes") says only the
  diff the request asks for. The references to "plugin signing" in
  those documents are inert under ADR-0021 but stay accurate as
  history. Flagged as Suggestion #2.

## Verification

```
$ .venv/bin/python3.12 -m pytest -q packages/llm_tracker/tests packages/llm_tracker_plugin_supabase_sink/tests
........................................................................ [ 31%]
........................................................................ [ 62%]
........................................................................ [ 93%]
..............                                                           [100%]
230 passed, 4 warnings in 7.16s
```

Pre/post comparison: 241 passing before this commit
(including 11 in `test_signing.py` + 3 signing-only tests in
`test_plugin_host.py` = 14 retired). 230 passing after, matching
241 - 14 + 3 = 230 (three of the retired tests had no replacement;
no new tests added). The four warnings are pre-existing
`DeprecationWarning: fork()` from `cli/manage.py`, unrelated to this
commit.

```
$ .venv/bin/python3.12 -m ruff check packages
Found 6 errors.
[*] 5 fixable with the `--fix` option.
```

The six errors are pre-existing (confirmed by `git stash`-baseline
run before applying changes): 3 in `tests/perf/report_first_token_latency.py`
(F541 / E501), 3 in `alembic/`-tree files + `cli/main.py` (I001
import-sorting inside function bodies). The cli/main.py I001 at
`from alembic.config import Config` was present in the original
file. This commit introduces zero new ruff findings.

Final signing-reference grep on the post-commit tree:

```
$ grep -r "sign" packages/ --include="*.py" -l | grep -v __pycache__
```

Returned matches are all unrelated:
- `design.md` references in docstrings.
- `signal` module / SIGINT etc. in `cli/manage.py`.
- "signs" / "signed" / "signals" in English prose (forwarder docstring,
  keyword_block plugin comment).
- "signature" of an `EgressClient.fetch` Protocol method in
  `test_egress_protocol.py` (Python function signature, not crypto).

No signing logic remains in non-test code.

## What's left / known limits

- `packages/llm_tracker_server/pyproject.toml` still lists `pynacl`
  (see Decisions above). Server package has no Python code that uses
  it today; safe to drop once the team confirms the server will not
  bring its own crypto layer.
- ADR-0008 still exists as `docs/decisions/0008-plugin-signing-trust-model.md`
  with **Superseded by ADR-0021** in its status line (set in the
  prior worklog's commit, unchanged here). It remains as historical
  context, per ADR convention.
- ADR-0017 §"Open questions" list still mentions "what survives of
  ADR-0008 signing" as open. ADR-0021 closed it, but ADR-0017 was not
  rewritten here (the previous worklog deliberately left it untouched
  to preserve a sealed ADR). One-edit follow-up if the team prefers
  inline "Resolved by ADR-0021" notes.
- The "signature_missing" / "signature_invalid" / "signing_key_not_in_registry"
  reason codes were never hardcoded constants in
  `storage/audit.py` or `storage/models.py` (those use free-form
  `detail_json`); they only existed as enum members in
  `plugin_host/signing.py:VerifyResult` and as audit detail strings
  written by `load_plugins`. Both removed by this commit. No data
  migration is required — the codes never reached a persistent
  schema column.

## Handoff

Three forward paths remain on the queue from the prior worklog:

1. **Phase 3c kick-off planning** (server build-out anchored on
   ADR-0018/0019/0020). The deck is now cleared of dead signing code.
   A `ralplan`-style consensus plan is the natural next step.
2. **ADR-#2 consent decision** (Phase-3a item #2). Still owed before
   any external testing of the central server. Operator-only demo not
   blocked. Legal/privacy input may take longer than internal ADR
   drafting; flag to start in parallel with Phase 3c.
3. **Server `pynacl` cleanup** (Suggestion #1). Small follow-up; only
   defensible if the team agrees no server-side crypto is planned.

**Suggested order**: 1 (Phase 3c planning) → run #2 in parallel → 3
opportunistically.

`HEAD` is now at `b446c3f`. Any session resuming via STATUS.md should
read this worklog before touching code: the trust/ module and
`plugin_host.signing` no longer exist; any new test or code that
imports them is rebuilding what ADR-0021 retired.

## Suggestions (untouched)

1. **Drop `pynacl` from `packages/llm_tracker_server/pyproject.toml`.**
   The server package has no Python code that imports it; the line
   dates to ADR-0007's planned TaskDefinition signing, which
   ADR-0017's central-server pivot superseded and ADR-0021's signing
   retirement makes inert. Held off here per the task's "Do NOT
   remove anything beyond this list" constraint, but worth a one-line
   follow-up commit if the team confirms.
2. **`docs/design.md` and `docs/roadmap.md` still reference plugin
   signing.** The references are historical and not load-bearing,
   but a future rewrite (owed once Phase 3c is underway, per the
   prior worklog's Suggestions) should excise them. Specifically:
   `design.md` §"Plugin signing trust model (operator's own key vs.
   our central key)" open question (line ~462), `design.md` lines
   251/306 ("signature catches tampering" / "signature check");
   `roadmap.md` Phase 1a checkbox "Manifest signature verification"
   (line ~72) — done-and-now-retired; `roadmap.md` Phase 3a item
   "What survives of ADR-0008 signing" (~line 143) is closed by
   ADR-0021.
3. **`packages/llm_tracker_plugin_supabase_sink/tests/test_e2e.py`
   docstring header** still says "Wires `PluginHost` + `EgressGuard`
   + `HostEgressClient` + the live `SupabaseSinkPlugin` together
   against a stubbed Anthropic upstream..." which is accurate, but
   the file's internal "Mode R + opted_in + correct manifest" framing
   in `STATUS.md`'s closed-prior-workstream section refers to a
   "manifest re-signing path used in CP9". That STATUS.md section
   already flags it as "will disappear when the code-removal
   checkpoint lands" — i.e. now. STATUS.md §"Prior workstream"'s
   bullet on Path 3 can be tightened in a future docs sweep but is
   not load-bearing.
