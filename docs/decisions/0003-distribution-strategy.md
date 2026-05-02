# ADR-0003 · Distribution strategy: PyPI (`pipx`) + remote rule sync

- **Status**: Proposed (under user review; needs revision after the
  framework pivot in ADR-0005 to cover separate plugin distribution)
- **Date**: 2026-05-01
- **Author**: Claude Cowork
- **Related**: `docs/distribution.md`

## Context

The proxy must run on the user's machine, so something has to be installed
locally. But the things we want to change frequently (TaskDefinition,
policies, message templates) move on a different cadence than the code
itself. Splitting the two cadences in distribution sharply lowers friction.

Option comparison: see `docs/distribution.md`.

## Decision

**Distribute a thin core via PyPI/`pipx`. Pull policies/rules from a remote
service and refresh them on the fly.**

- Code distribution: `pipx install llm-tracker` (private mirror possible).
- Rule/definition sync: at startup and periodically, the proxy pulls from
  the central API and caches into the local SQLite.
- Version check: notify-only by default. When a flag declares a hard
  upgrade, the proxy refuses to start.
- No automatic code download or install. (Friction outweighs benefit at
  research scale; security risk reduced.)

## Consequences

- Estimated user code-update cadence: **once a quarter or less**.
- TaskDefinition / block-message changes require nothing of the user.
- The central API needs a rule-sync endpoint with auth + signing.
- Decision deferred: private PyPI mirror vs. private package on the public
  PyPI.

### What we give up

- "Download once and run forever" single-binary UX.
- Forced auto-update (low value vs. security risk at this scale).

### Reversibility

Low to medium. As long as the PyPI package and rule-sync interface stay
stable, adding a single-binary build later is a separate track.

## Open questions

- Private PyPI mirror vs. private package on public PyPI.
- Rule sync auth model: shared token vs. per-user keys.
- Triggers for forced upgrade: which kinds of changes warrant it?
- **Post-pivot revision needed**: after ADR-0005 split the world into core
  + plugins, plugin distribution is its own concern (PyPI? Git? Operator's
  own repo?). This ADR will be revised before Phase 1 starts.
