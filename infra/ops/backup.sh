#!/usr/bin/env sh
set -eu

if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

backup_dir=${BACKUP_DIR:-./backups}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$backup_dir"
output="$backup_dir/release-guardian-$timestamp.sql"

docker compose exec -T db pg_dump \
    -U "${POSTGRES_USER:-release_guardian}" \
    -d "${POSTGRES_DB:-release_guardian}" \
    --clean --if-exists --no-owner > "$output"

printf 'Created %s\n' "$output"
