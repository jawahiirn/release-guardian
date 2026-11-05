# Milestone 6 security review

Review date: 2026-11-05

## Verified controls

- Provider secrets are encrypted at rest with AES-GCM and are excluded from API responses.
- Session cookies are HttpOnly and SameSite=Lax; state-changing routes require the CSRF header.
- GitLab access is read-only and host allowlisted.
- Organization-scoped queries verify membership before returning data.
- Notification payloads use sanitized facts and disable Discord mentions.
- The operational health endpoint is authenticated and returns status/count data only.
- Production Compose removes the database host port and binds API/web to loopback.
- Restore requires an explicit confirmation environment variable.
- Logs use structured JSON and do not include request bodies, cookies, or provider secrets.

## Release checks

- Run `ruff check .`, `mypy apps packages`, and `pytest` before release.
- Run frontend build, lint, unit tests, and the Playwright smoke suite against a clean stack.
- Verify cross-organization access returns 404/403 without resource details.
- Verify an invalid GitLab host is rejected and a notification failure is recorded without logging the webhook URL.
- Verify the backup can be restored into an isolated PostgreSQL database and the worker resumes with the matching master key.

## Known boundaries

The current MVP does not implement SSO/OIDC, team-specific ACLs, public registration, email delivery, webhook transport, or a separate instance administrator role. These remain explicit product boundaries rather than hidden assumptions.
