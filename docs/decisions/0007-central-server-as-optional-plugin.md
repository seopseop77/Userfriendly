# ADR-0007 · Demote the central server to an optional plugin (supersedes ADR-0004)

- **Status**: Accepted (supersedes ADR-0004)
- **Date**: 2026-05-01
- **Author**: Claude Cowork (user-approved)
- **Related**: ADR-0004, ADR-0005, ADR-0006

## Context

ADR-0004 sealed the demo central server stack as Supabase + Fly.io + same
repo. The implicit assumption was "in every deployment, data flows to a
central server."

That assumption broke when ADR-0005 / 0006 introduced the framework-first
model. Customer deployments (Mode L) send nothing externally. Mode A sends
metadata only. Only Mode R sends rich data outbound. So the "central
server" should not be a core component; it is a **reference plugin for
Mode R operators**.

## Decision

**1) The central server code is repackaged as a reference upload-sink plugin.**

- Package name (tentative): `llm_tracker_plugin_supabase_sink` (or a
  similarly named variant).
- Located in this same repo tree under
  `src/llm_tracker_plugin_supabase_sink/`. Splitting to its own repo is
  deferred to Phase 2.
- Behavior: in `on_persisted`, batches exchange records to the operator's
  Supabase Postgres.
- Required capabilities: `read_persisted_data`, `egress_http`.
- The operator enters their Supabase URL as a destination during manifest
  approval.

**2) The receiver app (`src/llm_tracker_server/`) stays as the operator-side
   ingestion service.**

- A FastAPI app the operator runs to consume and analyze data they
  receive in their Supabase.
- Fly.io deployment kept as a reference (not required).
- The core framework has *no compile-time dependency* on this package. Both
  packages remain independent.

**3) ADR-0004's technical decisions (Supabase, lock-in avoidance, Fly.io)
   are preserved as the recommended setup for the reference plugin.**

## Consequences

- Mode L users do not install this plugin. It is *off* from the start.
- Only Mode R operators install it and grant manifest approval.
- The friction of "every core install needs a central server" disappears.
  Core setup is simple.
- The path is open for collaborators to build alternative sinks (their own
  analytics backend, their company's SIEM, etc.).

### What we give up

- The intuitive feeling that "the core *is* the data-collection system."
- Immediate code sharing between core and server. Common types must move
  to a shared package (or live in the SDK).

### Reversibility

Low. As long as the plugin interface is stable, sinks can be swapped at
will. The decision stands so long as ADR-0005 stands.

## Open questions

- When to extract a shared `llm_tracker_common` (or SDK) module for types
  used by both sides.
- The user opt-in consent flow on entering Mode R — what screen / document
  does the user pass through?
