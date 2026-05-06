# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b checkpoint 6 complete)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (in progress)
- **Active task**: Verifier primitive landed; host wiring + bundled keys.toml + hello_world signing next.

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
2659284   security: ed25519 manifest signature verifier
1042f7e   docs: Phase 1b checkpoint 5 — mode×cap policy at load time
eb7bd67   security: mode capability policy at load time
186ad8c   docs: Phase 1b checkpoint 4 — content-level primitive landed
8ca5973   security: content-level ladder + per-mode ceiling
```

## Where we paused

Phase 1b checkpoint 6 complete (2026-05-06, commit 2659284).
ed25519 manifest signature verifier primitive landed:

- New `llm_tracker.plugin_host.signing`:
  - `VerifyResult` (`StrEnum`): `verified` / `signature_missing`
    / `signature_invalid` / `signing_key_not_in_registry` per
    ADR-0008.
  - `load_registry(toml_bytes)` parses `[[key]]` entries with
    `name` + hex `public_key`.
  - `verify_manifest_signature(manifest_bytes, sig_blob, registry)`
    returns `(result, signer)`; never raises on
    operator-controlled bytes (every malformed sig blob → `SIGNATURE_INVALID`).
- ADR-0008 deferred sub-decisions locked here: byte-exact
  canonicalization (no parse/round-trip), sig blob is TOML with
  `signer` + hex `signature` so we can distinguish
  `signing_key_not_in_registry` from `signature_invalid`. Storage
  location, signing CLI, and reference-plugin signing approach
  stay deferred to the host-wiring checkpoint.
- 16 new tests cover all four verifier outcomes plus a
  parametrized "malformed sig blob" matrix and registry parsing.
- **Important correction**: prior worklog/STATUS proposed a new
  `signature_rejected` audit kind. ADR-0008 §"Hard reject on
  failure" actually specifies `manifest_rejected` (with the reason
  in `detail_json`). The next checkpoint reuses the existing kind.

103/103 tests pass; new module + tests lint clean. The verifier
is **not yet wired into `PluginHost.load_plugins()`** — that's
the next checkpoint's job.

## Next single step

Wire the signature verifier into `PluginHost.load_plugins()` and
seal the chicken-and-egg by signing the `hello_world` reference
plugin. ADR-0008's hard-reject contract means these have to land
together (any unsigned plugin breaks all real entry-point
loads).

Concrete shape:

1. Pick signature storage location (sibling `plugin.toml.sig`
   is the natural pick given the verifier takes raw bytes;
   document in `docs/plugins.md`).
2. Land `packages/llm_tracker/src/llm_tracker/trust/keys.toml`
   with at least one developer pubkey. Private key stays
   off-repo (probably in `keyring`, already a declared dep).
3. Land a minimal `llm-tracker sign-plugin <path>` CLI
   (ADR-0008 deliverable; CLAUDE.md §10 authorization comes
   from the ADR).
4. Sign `hello_world`; commit the resulting `plugin.toml.sig`.
5. Wire `verify_manifest_signature` into `load_plugins()`
   between `_find_manifest()` and `denied_capabilities()`. On
   non-`VERIFIED` result, write `manifest_rejected` (kind
   reused; `detail_json` carries the verifier's reason) and
   skip the plugin.
6. End-to-end load-time tests mirroring the existing
   `manifest_rejected` / `capability_denied` patterns, plus an
   integration test that the bundled `hello_world` verifies
   cleanly through the real registry+sig pipeline.

Content-level hook-dispatch integration stays blocked on Cowork
ADRs (`min_content_level` manifest field; typed payload object).
Proxy-boot wiring deferred to Phase 1c.

## Blocking / decisions needed

- None. Phase 1b is fully unblocked: ADR-0008 sealed the signing trust
  model, so manifest signature verification can be implemented when its
  turn comes in the Phase 1b checklist.

## Progress

- [x] Design v0.1 written
- [x] Framework pivot v0.2
- [x] English-only documentation pass
- [x] ADRs 0001–0008 sealed (0004 superseded by 0007)
- [x] Phase 0 — core skeleton (CLOSED 2026-05-04)
- [x] Phase 1a — plugin SDK (CLOSED 2026-05-05)
- [ ] Phase 1b — security boundary hardening (in progress)
- [ ] Phase 1c — `scope_guard` plugin
- [ ] Phase 2+ — Mode R sink, third-party plugins

---

## Update rules (for Claude Code)

At every checkpoint, do these three as one atomic unit (CLAUDE.md §5.3):

1. `git commit` the code change (CLAUDE.md §11).
2. Append the new commit hash to the active worklog's "What was done"
   section, and rewrite the "What's left / Handoff" section as of *now*.
3. Refresh this STATUS.md:
   - Last-updated timestamp (YYYY-MM-DD).
   - Active worklog path.
   - Last 3–5 commits.
   - "Where we paused".
   - "Next single step".

If you don't bundle these three, the next session won't know where to pick
up.
