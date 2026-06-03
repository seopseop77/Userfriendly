#!/usr/bin/env bash
# Daily Postgres backup for the llm-tracker self-host stack (ADR-0042).
#
# Dumps the llm_tracker DB (custom/compressed format) plus the cluster
# roles to a SEPARATE physical disk (/srv/backup, sdb) so that losing the
# NVMe that holds the live data (/srv/llm-tracker/pgdata) does not lose the
# backups too. Keeps the newest $RETAIN daily dumps; writes a marker file
# mirroring the box convention in /srv/backup/last-backup.txt.
#
# Install (one line, runs as the operator user — must be in the docker group):
#   30 3 * * * /home/server-minseop/workspace/Userfriendly/scripts/pg-backup.sh >> /srv/backup/llm-tracker/backup.log 2>&1
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

CONTAINER=userfriendly-db-1
DB=llm_tracker
DBUSER=llm_tracker
DEST=/srv/backup/llm-tracker
RETAIN=14   # keep this many daily dumps (+ matching roles files)

ts=$(date -u +%Y%m%dT%H%M%S)
dump="$DEST/llm_tracker-$ts.dump"
roles="$DEST/roles-$ts.sql"

# Dump to a temp file on the same filesystem, then atomic mv — a crash
# mid-dump never leaves a truncated file under the real name.
tmp_dump=$(mktemp "$DEST/.tmp.dump.XXXXXX")
tmp_roles=$(mktemp "$DEST/.tmp.roles.XXXXXX")
trap 'rm -f "$tmp_dump" "$tmp_roles"' EXIT

docker exec "$CONTAINER" pg_dump -U "$DBUSER" -d "$DB" -Fc > "$tmp_dump"
docker exec "$CONTAINER" pg_dumpall -U "$DBUSER" --roles-only > "$tmp_roles"

mv "$tmp_dump" "$dump"
mv "$tmp_roles" "$roles"

sha=$(sha256sum "$dump" | cut -d' ' -f1)

# Retention: drop everything older than the newest $RETAIN.
ls -1t "$DEST"/llm_tracker-*.dump | tail -n +$((RETAIN + 1)) | xargs -r rm -f
ls -1t "$DEST"/roles-*.sql        | tail -n +$((RETAIN + 1)) | xargs -r rm -f

cat > "$DEST/last-backup.txt" <<EOF
backup_completed=$ts
dump=$(basename "$dump")
dump_sha256=$sha
roles=$(basename "$roles")
dumps_retained=$(ls -1 "$DEST"/llm_tracker-*.dump | wc -l)
EOF

echo "[$(date -u +%FT%TZ)] backup ok: $(basename "$dump") sha256=$sha"
