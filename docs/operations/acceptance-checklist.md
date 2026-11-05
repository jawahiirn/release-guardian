# Milestone 6 acceptance checklist

Run this checklist on a clean Linux Docker host before release:

- [ ] Copy `.env.example` to `.env` and set unique database and encryption secrets.
- [ ] Start with `docker compose up --build -d`.
- [ ] Confirm `/health/live` and `/health/ready` return success.
- [ ] Bootstrap the first administrator and sign in through the web UI.
- [ ] Confirm the dashboard shows a healthy worker heartbeat.
- [ ] Configure a GitLab integration, a Discord destination, and one monitored project.
- [ ] Trigger or simulate a pipeline event and confirm one event, one outbox row, and one delivery attempt.
- [ ] Stop and restart the worker; confirm the heartbeat returns and pending work is recovered.
- [ ] Run a database backup, restore it into an isolated database, and verify the application can read the restored data.
- [ ] Run Python and frontend quality checks plus the Playwright smoke suite.
- [ ] Review logs for JSON formatting and confirm no cookies, tokens, webhook URLs, or raw secrets appear.
