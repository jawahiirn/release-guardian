# Release Guardian

Release Guardian is a self-hosted release monitoring application. The MVP is advisory and read-only against GitLab: it observes release activity, analyzes evidence, and routes notifications without merging, deploying, rolling back, or changing repository code.

## Milestone 0 quick start

1. Copy `.env.example` to `.env`, replace the local database password, and set a random 32-byte base64 `ENCRYPTION_MASTER_KEY`.
2. Start the stack:

   ```sh
   docker compose up --build
   ```

3. Open the frontend at <http://localhost:5177>.
4. Check API liveness at <http://localhost:8000/health/live> and readiness at <http://localhost:8000/health/ready>.
5. Open Swagger UI at <http://localhost:8000/docs>, ReDoc at <http://localhost:8000/redoc>, or the raw OpenAPI document at <http://localhost:8000/openapi.json>.

The Docker development frontend uses polling for Vite file watching because Docker Desktop can drop native file-change events when the repository is mounted from Windows or macOS. Set `VITE_USE_POLLING=false` in `.env` to opt out on filesystems with reliable event forwarding.

## pgAdmin connection

With the Compose database running, register a PostgreSQL server in pgAdmin using:

- Host: `localhost`
- Port: `5433` by default (`POSTGRES_HOST_PORT` in `.env`)
- Maintenance database: the `POSTGRES_DB` value from `.env`
- Username: the `POSTGRES_USER` value from `.env`
- Password: the `POSTGRES_PASSWORD` value from `.env`

The database is published on localhost for development. The container still listens on port 5432 internally; the host port defaults to 5433 to avoid conflicts with an existing local PostgreSQL installation. Do not expose the database publicly in a production deployment.

The API and worker run `alembic upgrade head` before starting. PostgreSQL data is stored in the `postgres-data` named volume. Do not use these development credentials in a remotely exposed deployment.

Integration secrets are encrypted with `ENCRYPTION_MASTER_KEY` using AES-GCM. The key is loaded by both the API and worker at process start; provider credential replacement itself is live and does not require an API or worker restart. Keep the master key outside Git and back it up with the database. Changing the master key requires a separate re-encryption procedure and is not the same as rotating a provider credential.

After the stack is running, create the first administrator from the API container:

```sh
docker compose exec api python -m apps.api.app.bootstrap --email admin@example.com
```

The command prompts securely for the password and is idempotent. It refuses to create another bootstrap user after the first user exists.

## Local checks

Python tooling is defined in `pyproject.toml`; install the project and development extras with `uv sync --extra dev`, then run:

```sh
ruff check .
mypy apps packages
pytest
```

Frontend checks run from `apps/web` after `npm install`:

```sh
npm run build
npm run lint
npm run test
```

PostgreSQL integration tests use a separate ephemeral Docker database and never reset the development database:

```powershell
docker compose -f compose.integration.yaml up -d --wait
$env:TEST_DATABASE_URL = "postgresql+psycopg://release_guardian_test:release_guardian_test@127.0.0.1:55433/release_guardian_test"
uv run --extra dev pytest tests/integration -q
docker compose -f compose.integration.yaml down
```

Without `TEST_DATABASE_URL`, the PostgreSQL integration tests are skipped.

## Milestone 2 integration configuration

The current slice adds organization-scoped integration metadata, encrypted write-only secrets, live credential replacement, and audit records. After bootstrapping an administrator and creating an organization, use Swagger at `/docs` to call:

- `POST /api/v1/organizations/{organization_id}/integrations`
- `GET /api/v1/organizations/{organization_id}/integrations`
- `PUT /api/v1/integrations/{integration_id}/secret`

The secret is never returned by the API or written to audit metadata. Every secret replacement creates a new nonce and increments `config_version`; worker operations will resolve the current version at operation time as provider adapters are added in later slices.

The frontend now includes a sign-in screen and an Integrations workspace. It supports organization selection/creation, provider metadata entry, write-only secret replacement, and local configuration validation. The validation action is deliberately network-free; it does not send Discord/Pushover messages or contact GitLab/OpenAI yet.

## Identity administration

Organization owners and admins can create seven-day invitation tokens, list members, create teams, and assign organization members to teams through the versioned API. Invitation acceptance creates a user when the invited email is new, or verifies the existing user's password before adding membership. Raw invitation tokens are returned only by the create response for manual sharing and are stored only as hashes.

Authenticated users can replace their password after verifying the current password; other active sessions are revoked. Organization owners and admins can promote or demote non-owner members and remove them, which also removes their team assignments. Owner membership cannot be changed or removed through these endpoints.

The Organization workspace exposes member, invitation, team creation, and team-assignment controls. Invitees can open `/accept-invitation`, paste the one-time token, choose a password, and then sign in normally.

## Milestone 3 monitoring slice

The current monitoring slice adds GitLab project registration and a PostgreSQL-backed polling worker. The Projects workspace is available in the frontend after sign-in; it registers projects, displays polling state, schedules an immediate read-only poll, and shows recent observed events. The same operations are available in Swagger through `POST /api/v1/organizations/{organization_id}/projects`, `POST /api/v1/projects/{project_id}/poll-now`, `GET /api/v1/organizations/{organization_id}/projects`, and `GET /api/v1/organizations/{organization_id}/events`.

The worker persists polling checkpoints and canonical failed-pipeline events with bounded failed-job evidence. Event uniqueness prevents duplicate events when the same pipeline state is observed again. Actual GitLab requests are read-only and require the GitLab hostname to be listed in `GITLAB_ALLOWED_HOSTS`; the default is `gitlab.com`. The first monitoring tests use injected fixtures and do not contact a real GitLab account.

Each successful project poll also compares the configured production and staging refs through GitLab's read-only repository comparison API. A new candidate revision creates a deduplicated `release.composition` event containing the exact production and candidate SHAs, bounded included commits and changed paths, the latest observed staging CI status, and an explicit `qa_status` of `unknown`. Green CI is never treated as QA approval.

For GitLab fine-grained personal access tokens, `Project: Read` alone is not enough for polling. Grant the token `Pipeline: Read` for the project; this covers the pipeline and pipeline-job endpoints used by the worker. If your GitLab version exposes a separate job permission for the additional job metadata or trace endpoints added later, grant only its read permission. A legacy token with the `read_api` scope is an alternative for local testing.

## Milestone 4 analysis slice

New failed-pipeline events are analyzed by the worker. If an OpenAI integration is configured, the worker resolves its current encrypted secret at operation time and sends bounded, sanitized facts to the configured model (default `gpt-5-mini`) using a structured response schema. If no usable OpenAI integration is available, the event receives a factual `fallback` analysis instead of blocking polling. Analysis records are organization-scoped, versioned, deduplicated by event/evidence/model/prompt version, and visible in the observed-events panel. Discord/Pushover delivery remains a later milestone.

## Current scope

Milestones 0 and 1 provide the runtime, identity, and organization foundation. Milestone 2 includes integration configuration UI and provider-shape validation. Milestone 3 includes the GitLab Projects UI plus the first polling/event slice. Milestone 4 now adds grounded analysis and factual fallback records. Milestone 5 adds Discord notification delivery through a transactional outbox. See `spec.md` for the approved phased plan and security requirements.

## Milestone 5 notification slice

The first notification slice routes newly observed tracked-branch pipeline events to configured Discord integrations through a PostgreSQL transactional outbox. Both successful and failed pipeline states are deduplicated by pipeline and commit state. The worker resolves the current Discord webhook at delivery time, records each attempt, retries transient failures with backoff, and exposes delivery history at `/api/v1/organizations/{organization_id}/deliveries`. Pushover and configurable routing rules remain follow-up slices. The Integrations workspace also provides an explicit Discord test-notification action that does not require a GitLab change.

## Milestone 6 operational hardening

The authenticated health dashboard reports database, worker heartbeat, polling, and notification queue status. API and worker logs are emitted as structured JSON with request IDs for API calls. Use the production overlay in `compose.production.yaml` for static frontend assets, loopback-only service bindings, and restart policies. Backup/restore scripts, systemd units, launchd agents, the security review, and the clean-install acceptance checklist are in `docs/operations/` and `infra/`.
