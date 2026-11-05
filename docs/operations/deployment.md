# Deployment and operations

## Docker Compose development

The default stack runs PostgreSQL, API, worker, and the Vite development server:

```sh
docker compose up --build -d
```

The local UI is available at `http://127.0.0.1:5177`, the API at `http://127.0.0.1:8000`, and PostgreSQL is published on `localhost:5433` for development tools. The API and worker run migrations and the worker records a PostgreSQL heartbeat every cycle.

## Production Compose overlay

Use the production overlay to build static frontend assets, run them behind nginx, remove the public database port, and add restart policies:

```sh
docker compose -f compose.yaml -f compose.production.yaml up --build -d
```

Set `APP_ENV=production`, a strong `ENCRYPTION_MASTER_KEY`, a non-default database password, an explicit `CORS_ORIGINS`, and a reverse proxy with HTTPS before exposing the API beyond localhost. The production overlay binds API and web to loopback by default so a reverse proxy or VPN controls external access.

## Health checks

- `/health/live` confirms the API process is responding.
- `/health/ready` confirms the API can reach PostgreSQL.
- `/api/v1/admin/health` is authenticated and shows database, worker heartbeat, polling, and notification queue status without exposing secrets.

The web dashboard refreshes the authenticated health snapshot every 15 seconds. A stale worker heartbeat marks the overall status critical; polling errors or failed notification deliveries mark it degraded.

## systemd

The templates in `infra/systemd/` expect a source installation at `/opt/release-guardian`, a `release-guardian` service account, and `/etc/release-guardian/release-guardian.env` containing the runtime environment. After editing the paths and environment file:

```sh
sudo cp infra/systemd/release-guardian-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now release-guardian-api release-guardian-worker
sudo systemctl status release-guardian-api release-guardian-worker
```

## macOS launchd

The templates in `infra/launchd/` are user agents for a source/uv installation. Replace `REPLACE_ME`, copy them into `~/Library/LaunchAgents`, and load them with `launchctl bootstrap gui/$(id -u)`. Use `launchctl kickstart -k gui/$(id -u)/com.releaseguardian.worker` after an update.

## Updates

Pull the desired revision, review migrations, rebuild the images, and restart the stack. Keep the database backup and encryption key available before applying a migration. Do not commit `.env`, provider secrets, private keys, or production logs.
