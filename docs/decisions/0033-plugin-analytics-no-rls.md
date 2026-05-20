# ADR-0033 · `plugin_analytics` stays outside RLS

- **Status**: Accepted
- **Date**: 2026-05-21
- **Author**: Claude Code (interview + execution)
- **Related**: ADR-0018 (per-org RLS for user-data tables), migration
  0007 (`plugin_analytics` creation; the table docstring already named
  this posture but never elevated it), worklog
  `docs/worklog/2026-05-21-followup-cleanup.md`.

## Context

`plugin_analytics` was created by migration 0007 with a deliberate
"no RLS" choice — the docstring named it but no ADR pinned it.
The Phase-1 §"Queued follow-ups" list has carried "`plugin_analytics`
RLS axis — ADR-level revisit" as a pickable item since the schema
cleanup track closed (2026-05-18); this ADR settles it.

The table is written by the `analytics_sink` plugin and queried
out-of-band by operator tooling (Supabase MCP, ad-hoc SQL, future
dashboard). It is **not** read through any request-scoped path
today — there is no API endpoint that serves a `plugin_analytics`
row to an end user.

ADR-0018 makes the per-org RLS guarantee load-bearing for the
**user-data** tables (`exchanges`, `audit_log`). The mechanism is:
`AuthMiddleware` opens a per-request `AsyncSession`, sets
`SELECT set_config('app.org_id', '<uuid>', true)` on that session,
and every RLS policy reads `current_setting('app.org_id', true)` to
admit or reject rows. **The GUC is session-scoped** — it lives
inside the connection / session that ran the `set_config` call and
does not propagate to other connections.

`analytics_sink` writes through its own dedicated `AsyncEngine`
(constructed at `on_init` time from `LLMTRACK_DATABASE_URL`),
**not** through the request-scoped session. Two separate connections
into PostgreSQL — by design, because the plugin must be able to
write analytics rows even when the request session has already
committed or errored out. The GUC binding does not cross that
boundary.

## Options considered

1. **Add RLS to `plugin_analytics`, propagate the GUC into the plugin
   engine.** Every `engine.begin()` block in the analytics plugin
   would have to issue `SET LOCAL app.org_id = '<uuid>'` from
   `ctx.org_id` before the INSERT / UPSERT runs. That is the only
   way the existing RLS policy shape works — `current_setting` reads
   from the connection's local state, not from a global context.

   - Pros: consistent with user-data tables; one mental model for
     row visibility.
   - Cons: the analytics plugin's write path becomes four extra
     statements per exchange (SET LOCAL on each of the per-message
     UPSERTs + the analytics-row INSERT, all inside the same
     transaction); operator dashboards have to grow GUC-binding
     wrappers; complexity for no current consumer.

2. **Keep `plugin_analytics` outside RLS.** Document the choice as
   an ADR rather than an implicit docstring; rely on the application
   layer (every plugin / operator query carries `org_id` explicitly
   in its `WHERE`) for cross-org isolation.

   - Pros: matches the actual access pattern (operator tooling and
     plugin writes only); zero GUC plumbing into the plugin engine;
     ADR captures the trigger for future revisit.
   - Cons: cross-org isolation is enforced at the query layer rather
     than the DB layer — operator queries that forget the `org_id`
     filter would see all orgs. (Today this is by design — the
     operator needs the cross-org view for dashboarding.)

3. **Move the analytics engine onto the request-scoped session.**
   Reuses the `AuthMiddleware` GUC binding for free, so RLS would
   apply automatically.

   - Pros: one engine for everything; RLS comes along for free.
   - Cons: contradicts the design choice that motivated the
     separate engine — analytics must outlive the request session.
     A blocked exchange where the request session aborts before
     `on_persisted` runs would lose its analytics row. Same problem
     if the session has already committed and closed by the time
     `on_persisted` fires. Off the table.

## Decision

**Pick option 2 — `plugin_analytics` stays outside RLS.** Three
reasons:

1. **The GUC binding is connection-scoped and does not propagate to
   the analytics plugin's `AsyncEngine`.** Bridging that would
   require every `engine.begin()` block to issue
   `SET LOCAL app.org_id = ...`, repeated across the per-message
   UPSERT loop and the analytics-row INSERT — complexity with no
   payoff for a table no end-user-facing path reads.
2. **`plugin_analytics` is internal operator tooling only.** The
   threat model RLS guards against — cross-org query isolation
   reachable from a per-request session — does not apply here.
   Operator credentials already have full access by design (this is
   how dashboards work).
3. **Cross-org isolation is enforced at the application layer.**
   Every plugin / operator query that scopes data carries `org_id`
   in its `WHERE` clause. The `analytics_sink` plugin always writes
   `ctx.org_id` into the row; queries that aggregate across orgs
   (whole-dataset dedup ratio, cross-org cost dashboards) do so
   intentionally. There is no path today that joins
   `plugin_analytics` to a user request without already filtering
   on `org_id`.

## Consequences

- Operator dashboards and ad-hoc Supabase MCP queries see all orgs
  without needing any GUC binding. This matches the actual access
  pattern.
- Cross-org isolation for `plugin_analytics` lives at the application
  layer — every query that wants per-org scoping must filter on the
  `org_id` column explicitly. This is the same discipline the
  `analytics_sink` plugin's existing write path enforces.
- `conversation_messages` (migration 0015) inherits the same posture
  by association — it is keyed `(conversation_id, msg_index)` with
  `org_id` as a defense-in-depth column, written by the same plugin
  engine, and read out-of-band the same way.
- The choice is reversible: adding RLS to `plugin_analytics` later
  is a single migration (CREATE POLICY + GRANT) plus the
  `SET LOCAL` plumbing in `engine.begin()` blocks. No data migration
  needed.

## Open questions

- **Revisit trigger.** If `plugin_analytics` is ever exposed through
  a request-scoped session path — a dashboard API endpoint that
  serves rows back to an end user, a multi-tenant operator console
  with non-admin viewers — this ADR should be revisited. Today's
  threat model assumes the table is only read by operator tooling
  that already has cross-org authority.
- **`conversation_messages` parity.** The table follows the same
  posture by association (same write engine, same operator-only
  read pattern). If the revisit trigger above fires, both tables
  should be migrated together.
