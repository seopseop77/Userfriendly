# Current Status (resume entry point)

> **Updated by the active Claude Code session at every checkpoint.**
> A new session reads this file → the active worklog → `git log -5`, then
> executes "Next single step". See `/CLAUDE.md §5, §6` for the rules.

---

**Last updated**: 2026-05-06 (Phase 1b checkpoint 7 complete)
**Updated by**: Claude Code

## Current phase

- **Phase**: Phase 1b — security boundary hardening (cleanup pass in progress)
- **Active task**: EgressGuard now wired into proxy lifespan; signature verifier wiring + signing CLI is next (Checkpoint B).

## Active worklog

`docs/worklog/2026-05-05-phase1b-security.md`

## Recent commits

```
e2ee4f0   proxy: wire EgressGuard into lifespan
d089fc0   docs: Phase 1b checkpoint 6 — signature verifier primitive
2659284   security: ed25519 manifest signature verifier
1042f7e   docs: Phase 1b checkpoint 5 — mode×cap policy at load time
eb7bd67   security: mode capability policy at load time
```

## Where we paused

Phase 1b cleanup-pass checkpoint A complete (2026-05-06, commit
e2ee4f0). `proxy/app.py` lifespan now constructs an `EgressGuard`
and passes it into `PluginHost(..., egress_guard=guard)`; the guard
is also stashed on `app.state.egress_guard` for later forwarder use.
`cli/main.py start` boots uvicorn against `llm_tracker.proxy.app:app`
so the lifespan is the single wiring point — no CLI-side change
needed.

A new regression test (`test_load_plugins_populates_egress_manifests_and_audits_attempt`)
pins the contract: after `load_plugins()` the manifest is in
`EgressGuard._manifests`, and a subsequent `check()` writes an
`egress_attempt` audit row. 104/104 tests pass.

This is part of a Cowork-driven cleanup pass (A → B → C → D → E
→ F → G, then Gates 1/2 with stop-for-input). One scope decision
already taken: Checkpoint G's `allowed_modes` default removal
gets a small ADR-0009 (option (a)) rather than skipping the
validation tightening.

## Next single step

**Checkpoint B — signature verifier wiring + signing CLI**, as
one atomic unit with a mid-flight stop for user input.

1. Create `packages/llm_tracker/src/llm_tracker/trust/__init__.py`
   and `keys.toml` (initially empty `[[key]]` array). Land a
   `load_bundled_registry()` helper that calls
   `signing.load_registry()` on the file content via
   `importlib.resources`.
2. In `host.load_plugins()`, after `_find_manifest()` and before
   `denied_capabilities()`, locate the sibling `plugin.toml.sig`
   via `importlib.resources`, read manifest bytes byte-exact, and
   call `verify_manifest_signature(...)`. On any non-VERIFIED
   result, write `manifest_rejected` to `audit_log` with the
   reason and skip the plugin.
3. Add CLI subcommand `llm-tracker generate-key` (writes ed25519
   keypair to the OS keychain via `keyring`, prints public-key
   hex for the user to paste into `keys.toml`).
4. Add CLI subcommand `llm-tracker sign-plugin <plugin-pkg-path>
   --signer <name>` that reads `plugin.toml`, signs with the
   keychain-stored private key, and writes `plugin.toml.sig`
   (TOML: `signer`, `signature` hex).
5. **STOP** — append "decision needed" to the worklog and ping
   user in Korean. User runs `generate-key` and pastes the hex
   back, then runs `sign-plugin` against `hello_world` to produce
   the `.sig`.
6. After resume: paste hex into `keys.toml`, commit the `.sig`,
   add a regression test asserting `manifest_rejected` is written
   if the `.sig` is removed, run the full suite, commit the whole
   checkpoint as one unit.

Existing monkeypatch-based tests (`test_plugin_host.py`) will need
a stub registry/sig hook to bypass the verifier without breaking
hard-reject.

## Blocking / decisions needed

- None for Checkpoint B's setup phase. After step 4, the user
  must run two CLI commands locally before the checkpoint can
  close.
- Gates 1 (Transform handling) and 2 (hook payload routing)
  are deferred to their respective checkpoints; not blocking now.

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
