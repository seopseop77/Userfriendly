# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b checkpoint 5 complete)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (in progress)
- **Active task**: Checkpoint 5 done; manifest signature verification next.

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
eb7bd67   security: mode capability policy at load time
186ad8c   docs: Phase 1b checkpoint 4 — content-level primitive landed
8ca5973   security: content-level ladder + per-mode ceiling
249f8bd   docs: Phase 1b checkpoint 3 — host↔guard wiring landed
f1a31cf   security: wire PluginHost manifests to EgressGuard
```

## Where we paused

Phase 1b checkpoint 5 complete (2026-05-06, commit eb7bd67).
Mode-by-mode capability policy now enforced at plugin load time:

- New `llm_tracker.plugin_host.policy`: `MODE_DENIED_CAPABILITIES`
  table sourced from design.md §8. Today only Mode L denies
  `egress_http`; Modes A and R deny none (their runtime
  egress restrictions stay in EgressGuard).
- `denied_capabilities(mode, declared)` returns the offending
  subset; unknown mode raises `ValueError` (closed L/A/R, same
  convention as `content_levels.effective_ceiling`).
- `PluginHost.load_plugins()` now consults the policy after
  manifest validation, before `egress_guard.register()`. On
  denial it writes `capability_denied` (`detail_json` = `{mode,
  denied}`) and skips the plugin.
- 9 new tests: 8 in new `test_policy.py` (table shape, full
  parametrized (mode, capability) matrix, multi-declared subset,
  empty-declared, unknown-mode); 2 in `test_plugin_host.py`
  (Mode L rejects egress_http manifest; Mode R accepts the same).

87/87 tests pass; changed + new files lint clean.

## Next single step

Manifest signature verification — the last open Phase 1b line as
a pure implementation task. ADR-0008 sealed the trust model
(per-developer ed25519 keys, bundled public-key registry, verify
at install AND boot, hard reject on failure).

Concrete shape:

1. Re-read ADR-0008 to pin the on-disk shape of the bundled key
   registry before writing code.
2. Add a verifier module (likely `llm_tracker.plugin_host.signing`
   — confirm SDK vs host layering against ADR-0008): reads the
   registry, verifies a manifest signature, returns a typed
   result (verified / wrong-key / no-signature / bad-signature).
3. Wire into `load_plugins()` between `_find_manifest()` and
   `denied_capabilities()`: failure → `signature_rejected` audit
   row, skip. Mirrors existing `manifest_rejected` /
   `capability_denied` patterns.
4. Tests: fixture key + signed manifest covering verified,
   tampered, and unsigned cases; one load-time end-to-end test.

Content-level hook-dispatch integration stays blocked on Cowork
ADRs (manifest `min_content_level` field; typed payload object).
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
