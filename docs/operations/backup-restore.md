# Backup and restore

Release Guardian stores all users, organization configuration, encrypted provider credentials, events, analyses, and delivery history in PostgreSQL. The encryption master key is required to use encrypted credentials after a restore, so keep it in the same operator-managed secret store as the database backup.

## Create a backup

From the repository root while the Compose database is running:

```sh
BACKUP_DIR=./backups ./infra/ops/backup.sh
```

The script writes a timestamped SQL dump. Store the dump and the encryption master key separately from the application checkout, protect them with the same access controls, and test restores periodically.

## Restore a backup

Stop API and worker consumers first, then restore into the running PostgreSQL container:

```sh
docker compose stop api worker
CONFIRM_RESTORE=YES ./infra/ops/restore.sh ./backups/release-guardian-20261105T120000Z.sql
docker compose up -d api worker web
```

Restore is intentionally gated by `CONFIRM_RESTORE=YES` because it replaces current database contents. After restoring, verify `/health/ready`, sign in, inspect the organization list, and confirm the worker heartbeat before resuming monitoring.

## Master-key handling

Database recovery without the matching `ENCRYPTION_MASTER_KEY` preserves rows but makes provider credentials unusable. Changing that key is a separate re-encryption operation; do not replace it during an ordinary database restore.
