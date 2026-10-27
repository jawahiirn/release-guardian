# Release Guardian

Release Guardian is a self-hosted release monitoring application. The MVP is advisory and read-only against GitLab: it observes release activity, analyzes evidence, and routes notifications without merging, deploying, rolling back, or changing repository code.

## Milestone 0 quick start

1. Copy `.env.example` to `.env` and replace the local database password.
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
- Port: `5432`
- Maintenance database: the `POSTGRES_DB` value from `.env`
- Username: the `POSTGRES_USER` value from `.env`
- Password: the `POSTGRES_PASSWORD` value from `.env`

The database is published on localhost for development. Do not expose port 5432 publicly in a production deployment.

The API and worker run `alembic upgrade head` before starting. PostgreSQL data is stored in the `postgres-data` named volume. Do not use these development credentials in a remotely exposed deployment.

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

## Current scope

Milestone 0 provides the runtime foundation only. Authentication, organizations, integrations, monitoring, AI analysis, and notifications are intentionally not implemented yet. See `spec.md` for the approved phased plan and security requirements.
