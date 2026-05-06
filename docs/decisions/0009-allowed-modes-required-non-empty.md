# ADR-0009 · Plugin manifest `allowed_modes` is required and non-empty

- **Status**: Accepted
- **Date**: 2026-05-06
- **Author**: Claude Code (user-approved option (a))
- **Related**: `docs/worklog/2026-05-05-phase1b-security.md` (checkpoint
  13), ADR-0006 (deployment modes), `packages/llm_tracker_sdk/src/llm_tracker_sdk/manifest.py`,
  CLAUDE.md §10 (manifest schema is a public interface)

## Context

Until now, `PluginManifest.allowed_modes` defaulted to
`list(VALID_MODES)` — i.e. a plugin that omitted the field
implicitly declared itself runnable in **all** modes (L, A, R).

This is the wrong default for a security-first framework. Mode L
is the local-only deployment with the strictest egress posture;
silently auto-enrolling a plugin into L when its author never
considered the L scenario is an "open by default" failure mode.
The cleanup-pass audit flagged the default as a contract
violation against ADR-0006 §1.

`allowed_modes` is part of the plugin manifest schema, which
CLAUDE.md §10 lists as a public interface contract requiring an
ADR before changes.

## Options considered

1. **(a) Make `allowed_modes` required and non-empty.** Plugin
   authors must declare exactly which modes they support; any
   omission is a manifest validation error caught at install
   time.
2. **(b) Keep the current default.** Continue auto-enrolling
   silent plugins in all modes. Documented as a known gap.
3. **(c) Default to `["L"]`.** Conservative auto-default —
   "local only" if unspecified. Cleaner than (b) but still hides
   the decision from the author.

## Decision

**Pick option (a).** Two core reasons:

- **Security-first defaults**. Mode L's threat model is
  "highly sensitive data must not leave the machine"; enrolling
  a plugin in L without the author's explicit consent is a
  silent loosening of the operator's trust boundary. Forcing
  a declaration eliminates the silent path.
- **Explicit > magic** for plugin authors. Naming the modes a
  plugin supports is a few keystrokes; the manifest is
  authoritative documentation for operators reviewing a plugin's
  posture before installation.

Implementation: `allowed_modes: list[str] = Field(..., min_length=1)`
in `manifest.py`. Pydantic catches both the missing-field and
empty-list cases at validation time; the existing
`_validate_modes` validator continues to reject unknown mode
strings.

The `hello_world` reference plugin already declares
`["L", "A", "R"]` explicitly, so neither its manifest content
nor its `plugin.toml.sig` need to change.

## Consequences

- **Breaking change for any plugin that omitted `allowed_modes`.**
  None ship in this repo today, so the practical impact is zero.
  Any external prototype carrying a partial manifest will now
  fail load with a clear validation error pointing at the
  missing field.
- **Operator review surface improves**: every plugin manifest
  visibly declares the modes it claims; operators auditing
  installs see no implicit defaults.
- **Reversibility: low cost**. Reverting would mean restoring
  the `list(VALID_MODES)` default in one line. Plugins that
  start declaring `allowed_modes` after this ADR keep working
  under any future relaxation.

## Open questions

None. The change is self-contained.
