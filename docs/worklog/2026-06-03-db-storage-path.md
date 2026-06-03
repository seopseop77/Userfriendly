# 2026-06-03 · Pin the DB to an explicit bind-mount path

**Author**: Claude Code
**Session trigger**: User: "현재 local DB는 어디에 위치해있는거지?" →
"이게 어디에 위치하는 게 좋을까? ... 다른 user가 분석할 때도 쓸 수 있어야 ...
이 user 경로 밖에 위치해야 하는 건 아닐까?"
**Related**: ADR-0042 (open question "DB storage path" → resolved).

## Interpretation + framing correction

The operator asked where the DB should live so that *other users can analyze
it*, suspecting it should sit outside their home path. Two things were
clarified before acting:

1. **Path ≠ analyst access.** Postgres data files are an internal binary
   format (`/var/lib/postgresql/data`, owned by container uid 999, mode
   `0700`) that only the postgres server reads. Nobody analyzes by reading
   those files. Multi-user analysis is a **DB-role / connection** concern
   (a read-only role + SQL access), independent of the filesystem path.
2. **It was already outside the user home.** The named volume lived under
   `/var/lib/docker/volumes/...` (root-managed), and `/home` and `/` are the
   same disk (`/dev/nvme0n1p2`) — so "move out of my home" gained nothing
   physically.

Decisions taken (via AskUserQuestion):

- **Storage path** → move named volume → explicit **bind mount
  `/srv/llm-tracker/pgdata`** (discoverable for ops/backup; FHS `/srv` =
  service data).
- **Read-only analysis role** → **deferred** (not set up now).

## What was done

- Cold-migrated the data (chosen over fresh-start to preserve the demo token
  + audit log):
  1. `docker compose down` (kept the named volume).
  2. `docker run --rm -v userfriendly_pgdata:/from:ro -v
     /srv/llm-tracker/pgdata:/to alpine sh -c 'cp -a /from/. /to/ &&
     chown 999:999 /to && chmod 700 /to'` — preserves postgres ownership and
     the `0700` PGDATA permission postgres requires to boot.
  3. `docker-compose.yml`: `db.volumes` now `- /srv/llm-tracker/pgdata:
     /var/lib/postgresql/data`; removed the now-unused top-level
     `volumes: pgdata:`.
  4. `docker compose up -d`.
- Updated ADR-0042 open question → resolved.

## Verification

- `docker inspect userfriendly-db-1` → `bind /srv/llm-tracker/pgdata ->
  /var/lib/postgresql/data` (bind mount in use, not the named volume).
- Row counts identical before/after:
  `alembic=0023_view_session_id, orgs=2, api_tokens=1, audit_log=6,
  participant_registrations=0, exchanges=2`.
- `migrate` re-ran clean (already at head, no new DDL).
- All three containers healthy; tunnel still serves `/healthz` 200 on both
  `llm-tracker.userfriendly.win` and `signup.userfriendly.win`.

## Notes / leftovers

- The old **`userfriendly_pgdata` named volume is retained as a backup**.
  Once confident, remove it with `docker volume rm userfriendly_pgdata`.
- **Backups** (ADR-0042 open) still pending: a `pg_dump` cron to off-box
  storage. The bind-mount path makes this more discoverable but does not by
  itself create a backup.
- **Multi-user analysis** (deferred): when needed, create a `SELECT`-only
  role and decide the connection path (local socket vs. tunnel) and which
  tables/views to expose.

## Handoff

DB data now lives at the explicit host path `/srv/llm-tracker/pgdata` (bind
mount), data preserved and verified, stack + tunnel healthy. Old named
volume kept as a one-off backup. Unrelated next step is still the client
cutover (step 5) in `docs/worklog/2026-06-02-local-storage-migration.md`.
