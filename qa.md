# Release Guardian — Questions and Answers

## 1. Why does WebStorm show missing imports even though the project runs?

The application can run because the Docker container has the dependencies installed in its own `node_modules` volume. WebStorm may be inspecting the host filesystem, where the packages are not installed or where the package root is not configured correctly.

Check these items:

- Open `apps/web` as the frontend package root, or open the repository and ensure WebStorm detects `apps/web/package.json`.
- Run `npm install` from `apps/web`, not only from the repository root.
- Confirm `apps/web/node_modules` exists on the host if WebStorm is not using the Docker container's filesystem.
- In WebStorm, verify Settings → Languages & Frameworks → JavaScript → Libraries and Node interpreter point to the intended Node installation and package directory.
- If imports still appear unresolved, invalidate the IDE caches and restart after confirming `package-lock.json` is current.

Docker Compose currently mounts the project into the container and stores container dependencies in the named `web-node-modules` volume. That volume is separate from the host's `apps/web/node_modules`, which explains why Docker can run while the IDE reports unresolved modules.

## 2. I downloaded the React project's node modules. What does that change?

Installing from `apps/web` creates or updates the local dependency tree described by `apps/web/package.json` and locked by `apps/web/package-lock.json`. WebStorm can then resolve imports from the host filesystem. The Docker container still has its own dependency volume, so host installation and container installation are separate.

Use:

```powershell
cd apps/web
npm install
```

Do not commit `node_modules`; it is excluded by `.gitignore`. Commit changes to `package.json` and `package-lock.json` when dependencies change.

## 3. What do the packages do?

### Frontend runtime and build

- `react`, `react-dom`: UI components and browser rendering.
- `vite`: local development server and production bundler.
- `typescript`: static type checking.
- `@vitejs/plugin-react`: React support for Vite.
- `tailwindcss`, `@tailwindcss/vite`: utility styling foundation.

### Frontend data and UI

- `axios`: HTTP client for the FastAPI API, including credentials and interceptors.
- `@tanstack/react-query`: server-state caching, loading/error states, refetching, and mutation management.
- `vitest`: frontend unit and component test runner.
- `eslint`, `@eslint/js`, `typescript-eslint`: JavaScript and TypeScript linting.
- `shadcn/ui`: the project uses the shadcn approach—local, accessible components owned by the application rather than a closed widget library. The current `Button` is the first local primitive; more components will be added only when needed.

### Backend and persistence

- `fastapi`: typed asynchronous HTTP API framework.
- `uvicorn`: API process server.
- `sqlalchemy`: database engine and persistence abstraction.
- `psycopg`: PostgreSQL driver.
- `alembic`: versioned database migrations.
- `pydantic` and `pydantic-settings`: typed request, response, and configuration models.
- `argon2-cffi`: planned password hashing implementation for identity work.
- `pytest`: backend tests.
- `ruff` and `mypy`: Python linting and type checking.

## 4. Do I need a `.env` file?

Yes for local configuration, and it is good that you created one. Start from `.env.example`. The `.env` file is intentionally ignored by Git and must never be committed.

For the current Docker Compose milestone, the important values are:

```env
POSTGRES_DB=release_guardian
POSTGRES_USER=release_guardian
POSTGRES_PASSWORD=use-a-local-secret
APP_ENV=development
VITE_API_BASE_URL=http://localhost:8000
```

The current application does not yet store provider credentials or an application encryption key. Those will be added in later milestones. Use strong, operator-managed values before exposing the application beyond localhost.

For pgAdmin, use host port `5433` by default. Release Guardian maps host port `5433` to PostgreSQL’s container port `5432` so it does not conflict with another PostgreSQL installation on Windows.
