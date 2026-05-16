# ADR-0008 · Plugin signing trust model: per-developer ed25519 keys + bundled registry

- **Status**: **Superseded by ADR-0021 (2026-05-11).** Full retirement
  of the manifest-signing trust model. The original threat
  (user-side `plugin.toml` tampering) was eliminated structurally by
  ADR-0017's pivot to server-side plugin execution; ADR-0021 chose
  full retirement over deployment-time repurposing on YAGNI grounds.
  The code-removal checkpoint (signing module / CLI commands /
  trust registry / `.sig` files / loader verification step) is
  queued as a Phase-3c-prep housekeeping checkpoint per ADR-0021
  §Consequences; this status line is the documentation half. The
  "What remains deferred" subsection below (boot-time cache, key
  rotation, revocation) is moot.
- **Date**: 2026-05-05 (decision); 2026-05-11 (superseded)
- **Author**: Claude Cowork (user-approved; based on a prior conversation
  between the user and Claude)
- **Related**: ADR-0021 (supersedes this), ADR-0017, ADR-0005
  §Open questions (this ADR resolved the "plugin signature trust
  model" item; ADR-0021 retires the resolution), ADR-0006,
  `docs/design.md §6.3`, `docs/plugins.md §10`, `docs/roadmap.md §1b`

## Context

ADR-0005 chose an in-process plugin model for Phase 1, with hardened
security boundaries lifted by manifest signature verification. The signing
trust model — *whose* keys verify *what*, when, and what failure looks
like — was left as an open question. Phase 1b implements signature
verification, so we lock the model now.

The threat we want to defend against is **operator tampering with
`plugin.toml`** after the plugin was authored and packaged. Without
signing, an operator running the proxy could edit a plugin's manifest to
quietly add capabilities it never declared (for example, add `egress_http`
plus a new destination to a plugin that originally asked for none). The
capability-grant UX would still occur on first install, but the operator
controls their own machine and could re-approve the tampered manifest as
"the latest version." Signing makes such tampering detectable, and our
loader policy makes it actionable (refuse the load).

What signing does **not** defend against, by design at this phase:

- A malicious team member who already holds a signing key. The framework
  trusts the team.
- Compromise of a signing key. No revocation flow yet — see Open
  questions.
- Plugin code itself doing something unintended at runtime. Signing
  covers the manifest only; the SDK boundary, EgressGuard, and AuditLog
  defend the runtime.

Current scope: **all plugins are developed in-house by trusted team
members.** No third-party plugin authors. This narrows the design space
considerably and lets us avoid building a marketplace, key-issuance
service, or formal revocation infrastructure.

## Options considered

### (1) Whose key signs?

- **A. Per-developer ed25519 keypairs.** Each team member holds a
  personal signing key and can sign plugins they author independently.
- **B. Single project-wide signing key.** Maintainer holds the key; all
  plugins funnel through them for signing.
- **C. Per-plugin signing key.** Each plugin has its own keypair held by
  its primary author.

### (2) Where does the verifier find trusted public keys?

- **A. Bundled in the distributed core package.** Updating the trust set
  requires a core release.
- **B. Online registry fetched at install/boot.** Updates are instant;
  introduces a new infra dependency.
- **C. Trust-on-first-use with operator confirmation.** Easier ops; weaker
  security and worse UX.

### (3) When does verification run?

- **A. Install time only.** Catches tampering during distribution; misses
  post-install tampering.
- **B. Boot time only.** Catches the latest state; lets a tampered plugin
  install silently.
- **C. Both.** Defense in depth.

### (4) Failure mode?

- **A. Hard reject — refuse to load.**
- **B. Warn-and-continue with audit entry.**

## Decision

### (1) Per-developer ed25519 keypairs (Option A)

Each team member generates and owns a personal `(private, public)`
keypair. They sign the plugins they author with their private key. There
is no central signing authority; developer autonomy is the goal.

### (2) Public-key registry bundled in the core package (Option A)

The set of trusted public keys ships inside the core package — for
example, a frozen TOML at
`packages/llm_tracker/src/llm_tracker/trust/keys.toml` listing each
registered team member's name and ed25519 public key. Updating the trust
set (adding a new team member, removing a departed one) is a core release
operation.

A signature is **valid if it was produced by ANY public key currently in
the bundled registry.** This makes any team member's key sufficient: a
plugin authored by Alice and signed only with Alice's key is trusted by
all operators running a core whose registry contains Alice's pubkey.

### (3) Verification at both install time AND every proxy boot (Option C)

- Install time: catches tampering during distribution.
- Boot time: catches tampering after install (e.g., the operator manually
  edited `plugin.toml` between sessions).

ed25519 verification cost is roughly 100 µs per signature; per-boot
verification of a small set of plugins is operationally negligible.

### (4) Hard reject on failure (Option A)

A plugin whose manifest signature does not verify is **refused load**.
The core writes a `manifest_rejected` entry to `audit_log` with the
plugin name, the failure reason (`signature_missing` /
`signature_invalid` / `signing_key_not_in_registry`), and refuses to
register the plugin's hooks. There is no warnings-and-continue mode. This
aligns with `CLAUDE.md §1` (security first).

### Signing scope

The signature covers **the full canonicalized contents of `plugin.toml`**.
Any modification — added capability, comment removal, whitespace
shuffling, anything — invalidates the signature. **Phase 1b
resolution: byte-exact contents** (no parse / re-serialize round
trip). Picked because TOML round-trip would couple the signature to
whichever serializer's whitespace and quote conventions we ship; a
library upgrade or swap would silently invalidate every existing
signature. Byte-exact gives "what was signed" and "what is on disk"
literal equality.

### Key registry management

- The project maintainer owns `trust/keys.toml`. Pull requests adding or
  removing keys go through the maintainer.
- **Adding a new team member**: maintainer adds their public key to the
  registry, releases a new core version.
- **Removing a team member**: maintainer removes their public key,
  releases a new core version. *All plugins signed only by that key
  become invalid on the next core release.* Plugins also signed by another
  remaining key continue to verify.
- Best practice: encourage co-signing (two developers each sign a plugin)
  to reduce churn when a team member departs. Not required.

## Consequences

### What this enables

- End-user / operator tampering with `plugin.toml` is detectable. The
  capability grant the operator approved at install cannot be silently
  widened.
- Each developer ships and re-signs plugins on their own schedule. No
  bottleneck through a central signing maintainer.
- Audit log contains a forensic record of every rejected manifest.

### What this constrains

- The bundled registry must be kept current. Adding or removing a team
  member is a core release, not a config change. Acceptable for a small,
  slowly-changing team.
- Removing a key cascades to every plugin signed only by that key.
  Plugins authored by departing members must be re-signed by a remaining
  team member before the next release, or they break. Co-signing
  mitigates this.
- The trust model is intentionally flat: any registered key may sign any
  plugin. There is no per-plugin authorship enforcement (e.g., "only Bob
  can sign `scope_guard`"). Adding such constraints would be a future
  ADR.

### Known limitation: trust of the bundled registry itself

The `keys.toml` file ships *inside* the core package. An operator who
modifies the installed core can replace or extend the registry with their
own keys. There is no technical defense against this from inside the
package — at that point the operator is modifying the binary they
installed, and the trust assumption is the same as for any signed
software: *you trust what you install*. Documented; not solved at this
phase. A future ADR might layer on a maintainer-key signature over
`keys.toml` itself if this becomes a concern.

### Resolved in Phase 1b

- **Canonicalization.** Byte-exact contents of `plugin.toml` (see
  "Signing scope" above). Implemented in `plugin_host.signing.verify_manifest_signature`
  (worklog checkpoint 6, commit 2659284).
- **Signature storage format.** Sibling `plugin.toml.sig` next to
  the manifest. Picked because the verifier consumes raw bytes; the
  alternatives (`[_signature]` inline, separate `MANIFEST.sig`)
  would re-introduce TOML parsing into the canonicalization
  surface. Documented in `docs/plugins.md`. Implemented in
  `PluginHost._verify_manifest` (worklog checkpoint 8, commit
  3010aae).
- **Signature blob format.** TOML with two fields: `signer` (string,
  must match a `name` in the registry) and `signature` (hex-encoded
  64-byte ed25519 signature). Carrying the signer name in the blob
  lets the verifier distinguish `signing_key_not_in_registry` from
  `signature_invalid`. Implemented in `verify_manifest_signature`
  (worklog checkpoint 6).
- **Registry file format.** TOML `[[key]]` array, each entry with
  `name` and `public_key` (hex of the 32-byte ed25519 public key).
  Bundled at `packages/llm_tracker/src/llm_tracker/trust/keys.toml`.
  Implemented in `signing.load_registry` and the `trust.load_bundled_registry`
  helper (worklog checkpoints 6 and 8).
- **Signing tooling.** `llm-tracker generate-key <name>` (ed25519
  keypair, private half stored in OS keychain via `keyring`,
  service `llm-tracker-signing`) and `llm-tracker sign-plugin
  <plugin-pkg-path> --signer <name>` (writes the sibling `.sig`
  TOML blob). Implemented as Typer subcommands in `cli/main.py`
  (worklog checkpoint 8).
- **Reference-plugin signing.** Reference plugins shipped in this
  repo are **signed by an individual maintainer**, not by a
  build-bot key. The `hello_world` reference plugin was signed by
  `minseop` during checkpoint 8; `keys.toml` ships that single
  entry. Adding a build-bot key later is a one-PR follow-up that
  would also adjust `keys.toml` and the CI release workflow; not in
  scope for Phase 1b.

### What remains deferred

- **Boot-time verification cache.** A possible optimization keyed on
  `(manifest_bytes, signature_bytes, registry_hash)` to skip
  re-verifying unchanged plugins. Performance only; defer.
- **Key rotation policy.** When and how team members rotate their
  personal keys. Default for now: rotate on credible compromise or
  every N months at the maintainer's discretion. No formal cadence.
- **Revocation mechanism.** No way today to revoke a single
  signature while keeping the signer's pubkey trusted. A formal
  `revoked_signatures.toml` is a future ADR if a
  "revoked-but-key-still-trusted" scenario arises.

### Reversibility

Medium. The `keys.toml` format is a simple data file and trivially
extendable. Switching from "any-key-signs" to "per-plugin allowed
signers" is mechanical. Replacing ed25519 with another scheme would
require coordinated re-signing and a release.

## Open questions

See "What remains deferred" above. None block Phase 1b
implementation; each becomes its own ticket or follow-up ADR if
needed.
