# ADR-0021 · Full retirement of plugin manifest signing

- **Status**: Accepted; supersedes ADR-0008
- **Date**: 2026-05-11
- **Author**: Claude Cowork (user-approved; decision made in the
  2026-05-11 Phase-3a decision interview)
- **Related**: ADR-0008 (superseded), ADR-0017, `docs/STATUS.md`,
  `docs/roadmap.md §Phase 3a`

## Context

ADR-0008 introduced ed25519 manifest signing with a bundled trust
registry. The threat it defended was **operator/user tampering with
`plugin.toml` on a user's machine**. ADR-0017 moved plugin execution
server-side, where end users cannot reach plugin code. The original
threat is structurally eliminated.

ADR-0017 §Open questions left two paths:

- Retire signing entirely.
- Repurpose the signing primitive as a deployment-time trust gate
  (which contributor's keys may push plugins to prod, or which
  releases an enterprise self-hosted operator can verify).

The first is simpler now and accepts the cost of rebuilding from
scratch later. The second preserves existing code but pays ongoing
maintenance for a gate that, at the current team size, fires for one
person.

## Options considered

### A. Full retirement (chosen)

- Remove the signing module, CLI commands, trust registry, plugin-
  loader verification step, and existing `.sig` files.
- Trust root for server-side plugin loading becomes the deploy
  pipeline itself (git repo + CI + server filesystem permissions).

### B. Repurpose as deployment-time trust gate

- Keep the signing infrastructure, redefine "trusted keys" as
  "approved contributor public keys", run verification in CI before
  plugins reach prod.
- Future-ready for external contributors and enterprise self-hosted
  release distribution.

### C. Defer (keep code, leave policy undecided)

- Code stays but is dead. Decision pushed forward.

## Decision

**Adopt Option A — full retirement.**

Reasons:

1. **The original threat is gone.** ADR-0017 eliminates it
   structurally; the signing primitive solves a problem that no
   longer exists.
2. **YAGNI for the current team.** The contributor population is one
   person. Building a deployment-time trust gate for a one-person
   team is over-engineering.
3. **A future-fit redesign will be easier than a future-fit
   retrofit.** When external contributors or enterprise self-hosted
   distribution actually arrive, those requirements will be specific;
   designing then will fit them better than carrying forward a
   primitive built for a different threat model.

The trust root for server-side plugin loading is the **deploy pipeline
itself**: the team's git repository, CI, and the server filesystem.
There is no in-band cryptographic verification of plugin manifests on
the server.

## Consequences

### Code/artefact changes (Phase 3c, separate checkpoint)

The following are removed during a separate checkpoint of Phase 3c
(or earlier, as housekeeping):

- `packages/llm_tracker_sdk/src/llm_tracker_sdk/signing.py` and any
  signing helpers in the SDK.
- The plugin-host signature verifier (currently in
  `plugin_host.signing.verify_manifest_signature`) and its call site
  in the plugin loader.
- `packages/llm_tracker/src/llm_tracker/trust/keys.toml` and the
  `trust/` module.
- `llm-tracker generate-key` and `llm-tracker sign-plugin` CLI
  subcommands.
- The `keyring` / `llm-tracker-signing` dependency on the OS keychain
  (if no other code uses it).
- `packages/llm_tracker_plugin_supabase_sink/plugin.toml.sig` and any
  other `.sig` files in the repo.
- Signature-related audit-log reason codes
  (`signature_missing` / `signature_invalid` /
  `signing_key_not_in_registry`).
- Tests pinning signature behaviour.

### What this enables

- Plugin authoring surface shrinks: one less step in
  `docs/plugins.md`, no key generation, no signing CLI to learn.
- Plugin deployment path is one-pass: git → CI → server filesystem.
- The `trust/` module disappears from the core; the codebase loses a
  security primitive it no longer uses.

### What this forecloses

- Detection of post-deploy, in-place manifest tampering on the
  server. The mitigation is now "harden the server's filesystem and
  deploy permissions" — operations, not cryptography.
- An off-the-shelf trust mechanism for the first external
  contributor or first enterprise self-hosted operator. When those
  arrive, a new trust ADR is required; we may end up rebuilding
  something that resembles ADR-0008 but with different keys-and-
  policy.

### Reversibility

Low-to-medium. The code is small (couple hundred lines), and ed25519
libraries are off-the-shelf. The reversibility cost is in the
*policy* design (who signs what, when; how revocation works) — not
the cryptography. The policy will need a fresh design anyway,
fitted to the actual future need.

## Open questions

**None within this ADR.** The decision is to retire, and the
follow-up work is delete-only.

Forward-looking notes (not commitments):

- When external contributors or enterprise self-hosted distribution
  become real, open a fresh trust ADR — do not resurrect ADR-0008
  as-is; the future requirements will differ from the local-sidecar
  threat model.
- ADR-0008 must be marked **Superseded by ADR-0021** in the same
  documentation checkpoint that lands this ADR; the code-removal
  checkpoint is separate.
