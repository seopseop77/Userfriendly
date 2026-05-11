# ADR-0018 · Multi-tenancy boundary: per-org + Postgres RLS only

- **Status**: Accepted; resolves ADR-0017 §Open questions
  ("Multi-tenancy boundary on the server")
- **Date**: 2026-05-11
- **Author**: Claude Cowork (user-approved; decision made in the
  2026-05-11 Phase-3a decision interview)
- **Related**: ADR-0017, ADR-0019 (mode-taxonomy fate — co-decided),
  ADR-0020 (auth model — token claims populate the RLS context),
  `docs/roadmap.md §Phase 3a`, `docs/STATUS.md`

## Context

ADR-0017 moved the deployment surface to a central server operated by
the team. With every Claude Code request and response traversing our
infrastructure, the server must isolate one customer's data from
another's. ADR-0017 §Open questions left two coupled sub-questions:

1. What is the unit of isolation — organization-level, or user-level?
2. How is isolation enforced — at the database (Postgres RLS) or in
   application code?

The decision must be made before the Phase 3c server-side database
schema is written, because tenancy keys are first-class columns on
every user-data table. Retrofitting tenancy after launch is a
multi-table migration; retrofitting RLS after the fact is a security
audit. Both unblock — or block — the server build-out, so this ADR
lands ahead of Phase 3c.

## Options considered

### (1) Unit of isolation

- **A. Per-user only.** Every user is an independent tenant. `user_id`
  on every user-data table. Simplest schema for a single-user demo;
  no team-level sharing primitive built in.
- **B. Per-org only (chosen).** Users belong to an org; data is
  isolated at the org boundary. `org_id` on every user-data table.
  Maps cleanly onto enterprise self-hosted, where the operator
  effectively runs a single-org server.
- **C. Two-tier (org > user).** Both `org_id` and `user_id` columns.
  Most expressive (separates operator vs auditor vs user inside one
  org), but over-engineered for current scope.

### (2) Enforcement

- **A. Postgres RLS only (chosen).** Row-Level Security policies on
  every user-data table, scoped to the request's org. Database-level
  enforcement: an application bug cannot leak data across orgs.
- **B. Application-level only.** Every query carries an explicit
  `WHERE org_id = ?`. Simpler to learn but one missing predicate
  equals a cross-tenant leak — and the server stores raw prompts
  in plaintext.
- **C. Hybrid (RLS + service-role bypass for ops tooling).** RLS for
  the default access path; service-role key bypasses RLS for explicit
  operator tooling. Defers enforcement to two places.

## Decision

**1) Unit of isolation: per-org (Option B).**

Every user-data table — `exchanges`, `events`, `tool_calls`,
`audit_log`, and anything added during Phase 3c — carries
`org_id UUID NOT NULL REFERENCES orgs(id)` as its tenancy column.
Users belong to an org via membership; the data they generate is
owned by the org. Users *within* an org see each other's data by
default; *cross-org* isolation is hard.

Demo: a "team-of-1 org" is provisioned for the operator. Enterprise
self-hosted maps naturally — the operator runs a server with a single
org. Future multi-user-within-org work (operator role separation,
auditor view) is a follow-up that adds `user_id` as a secondary
column without breaking the org boundary.

**2) Enforcement: Postgres RLS only (Option A).**

RLS is enabled on every user-data table. Policies derive the current
org from `current_setting('app.org_id')` (set per request from the
validated agent→server token in ADR-0020) or, equivalently, from
`auth.uid()` resolved through an `org_members` table — whichever
Supabase pattern fits the server's request lifecycle. **No
application-code path issues queries that bypass RLS.**

Operator tooling (`/admin/...`) does *not* use a service-role key to
bypass RLS. Instead, operators have an explicit `admin` role
referenced inside RLS policies: policy branches grant broader
visibility when the requester's role is `admin`. This keeps the
enforcement surface inside Postgres rather than splitting it between
Postgres and application code.

## Consequences

### What this enables

- A single source of truth for tenancy enforcement — every read path
  goes through Postgres, every RLS policy is reviewable in one place.
- Enterprise self-hosted is structurally compatible: the operator
  provisions one org and the same policies hold.
- Schema stays simple: `org_id UUID NOT NULL REFERENCES orgs(id)` on
  each user-data table.
- ADR-0020's per-org tokens carry the org claim directly into the
  request's RLS context — no second lookup required.

### What this constrains

- All Phase 3c work must enable RLS on every new user-data table
  before deploy. Migration review must enforce this; a single
  forgotten table is a cross-tenant exposure.
- Cross-org analytics (e.g., aggregate drift metrics across all
  customers) requires a separate non-tenant-scoped pipeline — either
  a materialised view from a privileged role or an ETL into a
  separate non-RLS analytics table. Flagged for Phase 3d.
- Operator tooling cost: every admin feature must be expressible as
  an RLS policy branch. Some queries (e.g., "list all orgs") need
  policies that allow the admin role to see across orgs; this is a
  deliberate trade-off to keep enforcement unified.

### What this forecloses

- "Service-role-key everywhere" pattern, where the server bypasses
  RLS and rolls its own enforcement. Cheaper short-term, but the
  failure mode (cross-tenant leak on a single forgotten predicate)
  is unacceptable given the data being stored.

### Reversibility

Medium. Adding `user_id` as a finer-grained secondary tenancy column
later is a schema addition, not a breaking change. Moving from RLS to
application-level enforcement would be a large undertaking and is
explicitly not anticipated. Moving from per-org to per-user only
would be a backwards migration and is explicitly out of scope.

## Open questions

- **Org membership UX.** How users are added to orgs (invite, SSO,
  operator action) is left to Phase 3c. The data-model anchor
  (`org_members` table linking `user_id` ↔ `org_id` + role) is
  settled here; the UX is not.
- **`admin` role scope.** Org-level admin vs server-wide superadmin
  is left to Phase 3c. Both shapes fit inside the RLS-policy
  enforcement model.
- **Cross-org analytics surface.** Phase 3d concern.
