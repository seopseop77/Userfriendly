# ADR-0005 · Framework-first architecture + plugin model

- **Status**: Accepted
- **Date**: 2026-05-01
- **Author**: Claude Cowork (user-approved)
- **Related**: `docs/design.md §4–§6`, `docs/roadmap.md`, `docs/plugins.md`

## Context

The repository was initially scoped to a single-purpose product (Claude
drift tracking + scope enforcement + central data collection). Discussion
with the team surfaced two facts that change the shape:

1. **More features will keep coming.** Specifics aren't pinned down yet. We
   need to avoid having to edit the core for every new feature.
2. **Data-flow policy varies by deployment.** Customer scenarios refuse
   external egress; research scenarios want rich collection. The same
   core must safely support both.

Both pull toward the same answer: a *framework + plugin* model. The core
provides a consistent hook interface and a strong security boundary; every
*behavior* lives in plugins.

## Options considered

1. **Monolithic.** Everything in the core. Simpler for a single use case;
   each new feature edits the core, and customer/research data policy
   branches scatter throughout the code.
2. **Framework + in-process plugins (Python entry points).** The core loads
   plugins and dispatches via hooks. Plugins live in the same process.
   Lightweight.
3. **Framework + subprocess/WASM plugins.** Strong isolation. Heavy
   implementation and SDK overhead.

## Decision

**Option 2 — Python entry-point-based in-process plugin model.** Compensate
for the in-process limitation with policy.

- Plugins register via `llm_tracker.plugins` setuptools entry point.
- Each plugin ships a `plugin.toml` declaring hooks, capabilities, egress
  destinations, allowed modes, and DB namespace.
- The core verifies the manifest (with signature checks) before
  dispatching hooks.
- Eight hook points; an initial vocabulary of about ten capabilities. See
  `design.md §6.3`.
- All outbound HTTP is funneled through EgressGuard, which enforces the
  manifest's destination allowlist.
- All hook invocations, capability uses, and egress attempts go to
  `audit_log`.

To keep the door open for Phase 3 subprocess isolation, hook interfaces are
designed around *serializable inputs and outputs* — even though we pass
Python objects directly today, the boundary won't break if it later moves
to a serialization boundary.

## Consequences

- The core is a *feature-less host*. "Put it in the core" is almost always
  the wrong call.
- scope_guard, drift_metrics, the central upload sink — all separate
  packages.
- Collaborators add features without editing the core.
- A plugin SDK becomes a separate deliverable (`llm_tracker_sdk`, Phase 1).

### What we give up

- The simplicity of one package shipping everything.
- The hard ceiling of in-process isolation: a plugin that *intentionally*
  bypasses EgressGuard with a raw socket can do so in Python. Code review,
  static checks, and operator approval are mitigations; strong isolation
  is Phase 3.

### Reversibility

High cost to reverse. If the hook interfaces are well-defined in Phase
0–1, *adding* core capabilities without breaking the interface is cheap.
However, changing hook or capability vocabulary post-release would impact
every plugin. So §10 of CLAUDE.md (public interfaces) requires an ADR for
those changes.

## Open questions

- Plugin signature trust model — operator's own key vs. our project key
  vs. marketplace. Demo starts with operator's own key.
- Plugin distribution channel (PyPI / private mirror / direct git). ADR-0003
  needs revision.
- Timing of the in-process → subprocess migration.
