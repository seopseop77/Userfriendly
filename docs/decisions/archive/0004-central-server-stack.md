# ADR-0004 · Central server stack: Supabase + Fly.io + same repo

- **Status**: **Superseded by ADR-0007** (the central server is now an
  optional plugin, not a core component). The technical choices below
  (Supabase + Fly.io + vendor-lock-in avoidance) are preserved as the
  recommended setup for the reference upload-sink plugin.
- **Date**: 2026-05-01
- **Author**: Claude Cowork (user-approved)
- **Related**: `docs/design.md §13.1`, `docs/distribution.md`, ADR-0007

## Context

For the demo, we needed to lock the central-server stack. Option analysis
lived in `design.md §11.2`; the user chose the cloud free-tier (Option B)
explicitly with Supabase. App hosting and code location were delegated.

## Decision

**(1) DB: Supabase Postgres on the free tier.**

- Access is via standard Postgres protocol only (`postgresql://`).
- **Forbidden**: Supabase RLS auto-application, RPC, Edge Functions,
  Storage, Realtime, Auth-as-a-Service. Reason: vendor-lock-in avoidance
  (`design.md §11.8`, principle 2).
- Allowed: standard SQL, JSONB (universally supported), Alembic migrations.

**(2) App hosting: Fly.io free tier.**

- Dockerfile-based deployment via a single `fly.toml`.
- Persistent VM, so no demo-killing cold starts.
- Render's sleep behavior makes it a poor demo target.
- Cloud Run's free tier is generous, but the GCP console setup is heavier.

**(3) Code location: same repo, `src/llm_tracker_server/`.**

- Sharing model / event / TaskDefinition definitions with the local proxy
  (`src/llm_tracker/`) reduces drift risk.
- Package isolation is enforced by import discipline — server code cannot
  import client code; common types live in a shared module.

## Consequences

- The demo operator only needs one Supabase project and one Fly.io app.
  Cost: zero.
- All DB access is via SQLAlchemy 2.0 + Alembic. Standard Postgres only.
- Signing keys are generated locally and injected as Fly.io secrets
  (`fly secrets set`). The public key is embedded client-side for
  signature verification.
- Auto-backups: Supabase free tier ships daily. Additional backup is a
  Phase 1-tail concern.

### What we give up

- Supabase Auth/RPC/Realtime conveniences. We re-implement them ourselves.
- Migrating off Fly.io requires a `fly.toml` replacement (Dockerfile
  itself is portable).

### Reversibility

Low.
- DB migration: `pg_dump` → new Postgres → flip `DATABASE_URL`. Alembic
  revisions identical.
- Hosting migration: any Dockerfile-friendly PaaS works as-is.

## Open questions

- Whether to use Supabase Auth for enrollment vs. our own tokens. Demo
  starts with own tokens (this ADR can be amended later).
- Free-tier monitoring/alerting (Supabase 0.5 GB DB; Fly.io 256 MB RAM × 3).
