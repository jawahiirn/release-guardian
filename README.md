# Release Guardian

Release Guardian is a self-hosted release monitoring application. The MVP is advisory and read-only against GitLab: it observes release activity, analyzes evidence, and routes notifications without merging, deploying, rolling back, or changing repository code.

## Milestone 0 quick start

1. Copy `.env.example` to `.env`, replace the local database password, and set a random 32-byte base64 `ENCRYPTION_MASTER_KEY`.
2. Start the stack:

   ```sh
   docker compose up --build
   ```

3. Open the frontend at <http://localhost:5173>.
4. Check API liveness at <http://localhost:8000/health/live> and readiness at <http://localhost:8000/health/ready>.
5. Open Swagger UI at <http://localhost:8000/docs>, ReDoc at <http://localhost:8000/redoc>, or the raw OpenAPI document at <http://localhost:8000/openapi.json>.

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

## Milestone 2 integration configuration

The current slice adds organization-scoped integration metadata, encrypted write-only secrets, live credential replacement, and audit records. After bootstrapping an administrator and creating an organization, use Swagger at `/docs` to call:

- `POST /api/v1/organizations/{organization_id}/integrations`
- `GET /api/v1/organizations/{organization_id}/integrations`
- `PUT /api/v1/integrations/{integration_id}/secret`

The secret is never returned by the API or written to audit metadata. Every secret replacement creates a new nonce and increments `config_version`; worker operations will resolve the current version at operation time as provider adapters are added in later slices.

## Current scope

Milestones 0 and 1 provide the runtime, identity, and organization foundation. Milestone 2 currently provides the first integration configuration slice; provider connection tests, GitLab polling, AI analysis, and notification delivery remain future milestones. See `spec.md` for the approved phased plan and security requirements.
