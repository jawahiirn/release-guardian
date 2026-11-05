#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
    printf 'Usage: %s BACKUP.sql\n' "$0" >&2
    exit 2
fi
if [ "${CONFIRM_RESTORE:-}" != "YES" ]; then
    printf 'Restore replaces the current database. Re-run with CONFIRM_RESTORE=YES.\n' >&2
    exit 3
fi

if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

docker compose exec -T db psql \
    -U "${POSTGRES_USER:-release_guardian}" \
    -d "${POSTGRES_DB:-release_guardian}" < "$1"
printf 'Restored %s\n' "$1"
