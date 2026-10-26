# Release Guardian — Product & Engineering Specification

**Status:** Implementation-ready draft  
**Version:** 0.1.0  
**Audience:** Codex coding agents, maintainers, reviewers  
**Primary deployment:** Independent self-hosted instance (macOS, Linux VPS, Docker)  
**Primary workflow:** GitLab release monitoring, AI-assisted investigations, Discord/Pushover alerts

> **Agent instruction:** This document is the source of truth for the MVP. Implement in vertical slices; do not silently expand scope. If an ambiguity blocks implementation, document the decision in `docs/decisions/` and choose the simplest secure, portable option. Never deploy, rotate live credentials, or send production notifications without operator approval.

## 1. Product overview

Release Guardian is an installable, always-on, multi-user web application that monitors GitLab projects and release branches, detects important pipeline and merge-request events, analyzes failures and release composition, and delivers actionable alerts through configurable notification providers. It runs on a developer's Mac or a VPS without requiring a public endpoint. Its dashboard remains usable while the worker operates in the background.

### 1.1 Core goals

1. **Portable and continuously running:** same codebase works in Docker Compose, Linux systemd, or macOS launchd; no public URL required for basic monitoring.
2. **Multi-user and tenant-aware:** users can belong to multiple organizations; organizations own monitored projects and shared integrations; users can maintain personal notification destinations.
3. **Live configuration and secret rotation:** authorized users update GitLab, OpenAI, Discord, and Pushover credentials without restart or redeployment.
4. **Extensible notifications:** Discord and Pushover at MVP, email later, via provider-neutral contracts.
5. **Trustworthy release intelligence:** distinguish objective GitLab facts, AI hypotheses, and unknown QA/approval status.
6. **Safe automation:** read-only GitLab access, advisory AI output, no autonomous merges, deployments, rollbacks, or secret exposure.
7. **Practical agent development:** Codex can implement modules with tests and clear acceptance criteria.

### 1.2 Non-goals for MVP

- Native desktop GUI, Electron/Tauri shell, mobile apps, hosted SaaS, cross-instance federation/registry.
- Automatic code fixes, pushes, merge approvals, deployments, rollbacks.
- Interactive Discord slash commands or a persistent Discord bot (use incoming webhooks first).
- Email delivery (reserve adapter and settings schema, implement next phase).
- Full QA approval workflow, complex team-level ACLs, SSO/OIDC, distributed multi-node execution.
- General-purpose autonomous multi-agent orchestration.

## 2. Decisions and assumptions

| Area | MVP decision | Rationale |
|---|---|---|
| UI | React 19, TypeScript, Vite, Tailwind CSS, shadcn/ui, TanStack Query | Familiar, fast, browser-based administration |
| API | Python 3.12+, FastAPI, Pydantic v2 | Typed async HTTP API |
| Persistence | PostgreSQL, SQLAlchemy 2, Alembic | Concurrent users, durable outbox and audit |
| Background processing | Separate Python worker with PostgreSQL-backed job claiming | Avoid Redis dependency in MVP |
| Scheduling | Worker-owned periodic polling and recovery jobs | No public URL needed |
| AI | OpenAI Python SDK, structured outputs | Simple first-pass analysis |
| Deep analysis | Codex SDK/CLI integration behind an optional adapter; phase 2 | Repository-aware investigation is heavier and riskier |
| Frontend auth | Backend-managed opaque session in HttpOnly cookie | No browser token storage |
| Deployment | Docker Compose is the initial deployment target; runtime remains portable for later launchd/systemd templates | Portable service installation |
| Tenant model | Independent instances, organization isolation within each instance | No central cloud dependency |
| Notification providers | Discord webhook and Pushover adapters | Small MVP, extensible design |
| GitLab transport | Polling first; webhook adapter later | Works behind NAT on a laptop |
| GitLab branches | Configurable branch roles (`development`, `staging`, `production`), defaults `Develop`, `Stage`, `Main` | Avoid hard-coded branch names |
| Administrator bootstrap | CLI-based administrator creation with secure password input and idempotent bootstrap checks; one-time setup tokens deferred | Safe, operator-controlled installation |
| Organization creation | Authenticated users may create organizations by default; an instance policy can disable unrestricted creation; public registration remains disabled by default | Support self-service without opening public registration |
| Default polling | 300 seconds per project, configurable after creation, with validation, jitter, retry/backoff, and persisted state | Predictable load without setup friction |
| Default AI model | `gpt-5-mini`, selected through runtime configuration and an AI provider abstraction | Avoid hardcoded business logic and permit substitution |
| First vertical slice | Complete pipeline-failure workflow through evidence, grounded analysis, routing, delivery, and history | Validate the highest-value workflow early |

**Important:** “Registry” means the organization/team directory *inside one installation* for MVP. Federation across independent installations is deferred.

## 3. Users, roles and authorization

### 3.1 Personas

- **Instance administrator:** bootstraps installation, manages global operational settings and user provisioning; cannot retrieve plaintext tenant secrets.
- **Organization owner:** manages organization, memberships, projects, integrations, notification rules.
- **Organization admin:** manages projects/integrations/members except ownership transfer or organization deletion.
- **Organization member:** views authorized projects, reports and notification history; manages personal destinations.

### 3.2 Tenant boundaries

- Users may belong to multiple organizations via memberships; switching organization changes API authorization context.
- Organization-scoped records MUST include `organization_id`, enforced in every service/repository query. Never trust a client-supplied organization ID without verifying membership and permissions.
- Personal notification destinations belong to a user; organization destinations belong to an organization. Organization-wide routing may use only approved organization destinations. Personal destinations may receive alerts only for projects that user can access.
- MVP teams are named groups with membership, used for display and future routing. Do **not** assume teams provide independent data isolation; organization is the security boundary. Team/project ACLs are phase 2.
- First install creates a one-time bootstrap admin via a CLI command or one-time setup token; public registration is disabled by default. Admins invite users via single-use expiring invitation links (manual link sharing is sufficient without email).
- Passwords hashed with Argon2id; session IDs random and stored hashed server-side; HttpOnly, SameSite=Lax cookies and Secure on HTTPS. CSRF protection on state-changing requests, origin checks, login rate limits, session expiry/revocation. Local HTTP only on loopback for development; remote production requires HTTPS.

### 3.3 Authorization matrix

| Action | Instance admin | Org owner | Org admin | Member |
|---|---|---|---|---|
| Configure instance/bootstrap | Yes | No | No | No |
| Create organization | Yes | Yes (new org) | Yes (new org) | Yes (new org) |
| Manage organization membership | No implicit tenant access | Yes | Yes | No |
| Manage shared GitLab/AI/provider integrations | No implicit tenant access | Yes | Yes | No |
| Configure monitoring/routing | No implicit tenant access | Yes | Yes | No |
| Read org reports/history | No implicit tenant access | Yes | Yes | Yes |
| Configure own destinations | Yes | Yes | Yes | Yes |
| View plaintext saved secrets | Never | Never | Never | Never |

Instance administrators operate the infrastructure, not arbitrary organization data. Any break-glass access must be an explicit, audited future feature.

## 4. MVP user journeys

### 4.1 Installation

1. Operator installs Docker and Docker Compose or uses documented local Python/Node prerequisites.
2. Operator supplies database connection, app public/base URL, encryption master key and initial bootstrap configuration through secure local setup (never committed to Git).
3. Migrations run; admin is bootstrapped once; API, worker, and frontend become available.
4. Application health page shows DB, worker heartbeat, poller status, and notification delivery health.
5. Restarting the service preserves users, configurations, event cursors, jobs and history.

### 4.2 Organization onboarding

1. User signs in, creates organization, invites members, and optionally creates teams.
2. Admin registers a GitLab connection using a least-privilege token and tests access.
3. Admin selects one or more GitLab projects and maps development/staging/production branches.
4. Admin sets up Discord and/or Pushover destinations and sends a test notification.
5. Admin creates routing rules; monitoring begins automatically.

### 4.3 Runtime credential rotation

1. Authorized user opens an integration, sees metadata, status, last four characters/fingerprint where safe, and `Replace credential`; never sees stored secret.
2. User submits replacement over authenticated HTTPS or local loopback session.
3. Backend validates syntax, optionally tests against provider, encrypts and atomically activates a new credential version. Failed tests can be overridden only through an explicit warning and authorization.
4. Subsequent jobs resolve the new credential version without process restart. In-flight jobs use their already acquired version; retries re-resolve current credentials.
5. System records who rotated it, when, which integration, and whether test succeeded; **never** stores raw secret in logs or audit records.
6. Old secret is no longer used and is deleted from active storage; any historical encrypted versions retained for audit must exclude secret material.

### 4.4 Stage pipeline failure

1. Poller observes new failed pipeline for a monitored staging branch.
2. Event is deduplicated and persisted with GitLab links and objective facts.
3. Collector fetches failed jobs and bounded sanitized log excerpts.
4. Analysis service produces structured summary: observed failure, likely causes, supporting evidence, recommended checks, uncertainty.
5. Notification router applies organization rules; delivery worker sends Discord and optionally Pushover.
6. Dashboard shows the report, evidence, timestamps, AI status and delivery attempts.

### 4.5 Release composition assessment

1. Poller observes a merge request targeting production or a new staging revision.
2. Collector compares production and staging refs (or MR source/target refs as applicable), obtains commits and associated MRs when possible.
3. System identifies changes present in candidate release but not production, and the latest CI results.
4. AI summarizes areas affected and potential risks. QA readiness is `UNKNOWN` unless a trusted configured approval source exists; MVP does not infer approvals from green CI.
5. Report is advisory; no automatic promotion.

## 5. Functional requirements

Use IDs in code, tests and PR descriptions.

### FR-001 Installation and runtime

- Ship `compose.yaml` with `web`, `api`, `worker`, `db`; frontend may be served as static assets through a small web server/reverse proxy.
- Support `uv run` API/worker and `pnpm dev` frontend for local development.
- Document `launchd` and `systemd` service examples for non-container installs, including start-on-login/boot, restart-on-failure and logs.
- Include graceful shutdown and readiness/liveness endpoints; worker resumes unfinished eligible jobs after crash.
- Running on a laptop behind NAT must work via polling.

### FR-002 Users and organizations

- Login/logout, password change, invitation acceptance, organization creation/switching, membership management, role enforcement.
- Teams CRUD and team membership can be minimal; no team-specific ACL in MVP.
- Tenant isolation tests must prove cross-org resources return 404/403 without leaking existence/details.

### FR-003 GitLab integrations

- Support multiple GitLab connections per organization; base URL configurable for gitlab.com or self-managed GitLab.
- Token stored encrypted; test connection and list accessible projects.
- Project registration stores GitLab project ID, connection ID, configured branch roles, polling interval, enabled state.
- Minimum monitoring: pipeline transitions, new/updated merge requests targeting configured branches, staging vs production changes.
- Prefer GitLab API endpoints and conditional fetching/pagination. Respect rate limits and `Retry-After` when available.
- Track per-project cursor/checkpoint; avoid missing changes during restart by overlapping time windows plus deduplication.
- When refs are missing or GitLab permissions are insufficient, show a diagnostic rather than fabricate results.

### FR-004 Event ingestion and analysis

- Canonical event envelope: `id`, `organization_id`, `project_id`, `source`, `source_event_key`, `event_type`, `occurred_at`, `observed_at`, `payload_version`, `facts`.
- Unique `(source, project_id, source_event_key, event_type, meaningful_state_version)` for idempotency.
- Deterministic checks run before AI; AI calls only on material state changes or explicit re-analysis.
- AI responses use strict typed schemas; include `summary`, `observations`, `hypotheses`, `evidence_refs`, `recommended_actions`, `uncertainties`, `model`, `prompt_version`.
- Distinguish facts from hypotheses in UI and notifications; no unverified QA or security claims.
- AI failures must not suppress objective alerts: send a factual fallback message and record analysis error.
- Sanitize logs and diffs for credentials/PII; enforce size/token caps; never feed full repository or arbitrary unbounded logs by default.
- Prompts treat code, MR text, and logs as untrusted data, never as instructions. No model tool with write access in MVP.

### FR-005 Notification provider framework

- Provider-neutral `Notification`, `Destination`, `DeliveryResult`, and `NotificationProvider` interfaces.
- MVP adapters: Discord incoming webhook; Pushover REST API. Email adapter reserved for future SMTP/provider API.
- Provider-specific configuration schemas and validation; secret references rather than plaintext in queued jobs.
- Rules match organization, project, event type and severity; destination enable/disable and test send.
- Persistent outbox, retry with exponential backoff/jitter, terminal failure state, manual retry; provider failures isolated.
- Deduplicate on `(event_id, destination_id, notification_kind)`; keep delivery attempt history and provider response codes (redacted).
- Pushover urgent alerts only by explicit rules; Discord routine channel is default.

### FR-006 Dynamic configuration

- Persist configuration in PostgreSQL; cache may be used only with explicit invalidation/version checking.
- Updates are atomic, audited and effective for new jobs without restart.
- Secrets encrypted at rest using authenticated encryption (e.g. AES-GCM) with a separately supplied master key; nonce unique per encryption operation; key identifier/version stored.
- Master key rotation is a separately documented operator procedure; do not conflate with runtime provider-token rotation. Master key may require coordinated restart/re-encryption in MVP.
- Credential metadata API must never return plaintext; secret-bearing fields write-only.
- Reject unsafe external integration URLs where SSRF risk exists: allow HTTPS by default, validate redirects and DNS/IP policy; self-managed GitLab private endpoints require explicit operator allowlisting.

### FR-007 Dashboard

- Responsive web UI with pages: Sign In, Organizations, Teams, Projects, Integrations, Notification Destinations, Routing Rules, Activity/Reports, Analysis Detail, Delivery History, Settings/Health.
- Clearly show observed facts vs AI inferences and unknown states.
- Show last poll, last successful analysis, next retry, failed integration tests, and worker heartbeat.
- Support loading/empty/error states, keyboard accessibility, and confirmation on destructive changes.
- Do not embed provider secrets in client bundles or localStorage.

### FR-008 Audit and observability

- Structured JSON logs with correlation IDs for event, analysis and delivery.
- Audit integration creation/update/rotation, project configuration changes, membership changes and rule changes.
- Metrics/counters: poll success/failure, event lag, analysis failures, notification success/failure, queue age, worker heartbeat.
- API health checks must not disclose sensitive operational details to unauthenticated users.

## 6. Architecture and module boundaries

```text
release-guardian/
  apps/
    web/                  # React/Vite UI
    api/                  # FastAPI entrypoint, HTTP routes, auth
    worker/               # poller, jobs, outbox delivery
  packages/
    core/                 # domain models, contracts, rules, services
    persistence/          # SQLAlchemy models, repositories, migrations
    integrations/
      gitlab/             # API client, collectors, polling adapter
      ai/                 # OpenAI adapter; Codex adapter later
      notifications/
        discord/
        pushover/
        email/            # interface/schema only until phase 2
    security/             # secrets, sessions, RBAC, audit helpers
  infra/
    docker/
    systemd/
    launchd/
  tests/
    unit/
    integration/
    e2e/
  docs/
    decisions/
    operations/
  compose.yaml
  .env.example
  README.md
  spec.md
```

Python package boundaries are logical, not independent deployable microservices. The API and worker import shared packages. No direct SQL in HTTP handlers; no GitLab or Discord SDK calls in domain logic. Frontend consumes versioned REST endpoints.

### 6.1 Processing pipeline

```text
GitLab poller (future: webhook receiver)
  -> normalize + persist event (idempotent)
  -> deterministic policy/evidence collection
  -> enqueue analysis job (if needed)
  -> structured AI analysis (or factual fallback)
  -> create notification outbox entries by routing rules
  -> delivery workers resolve current credentials
  -> Discord/Pushover
  -> report, audit, metrics
```

### 6.2 Worker and queue behavior

- PostgreSQL jobs table with states `queued`, `leased`, `succeeded`, `retryable_failed`, `dead`.
- Workers claim jobs using `FOR UPDATE SKIP LOCKED`, lease expiry and heartbeat; crashed worker jobs are reclaimed.
- Use bounded concurrency and per-integration rate limiting; no in-memory-only queue for critical notifications.
- One active poll lease per monitored project to prevent duplicate pollers. Multiple instances against different databases remain independent and may notify twice; warn operators to designate one monitoring owner per GitLab project.
- At-least-once processing; idempotent event/notification creation. Exactly-once delivery cannot be guaranteed for external providers.

### 6.3 Notification contract (illustrative Python)

```python
from typing import Protocol

class NotificationProvider(Protocol):
    async def validate_config(self, config: dict) -> None: ...
    async def send(self, notification: "Notification", destination: "Destination", credentials: "ResolvedCredentials") -> "DeliveryResult": ...
```

Credentials are resolved at dispatch, not serialized into jobs. Providers do not query organization data directly. Provider-specific formatting happens in the adapter; shared message contains title, summary, severity, evidence links and structured metadata.

## 7. Data model (initial)

All tables use UUID primary keys and UTC timestamps. Add indexes for tenant and frequently queried status/time fields.

| Table | Key fields / relationships |
|---|---|
| `users` | email unique, password_hash, status |
| `sessions` | user_id, hashed_session_token, expires_at, revoked_at |
| `organizations` | name, slug, owner_id |
| `memberships` | organization_id, user_id, role, unique pair |
| `teams` | organization_id, name |
| `team_memberships` | team_id, user_id, unique pair |
| `invitations` | organization_id, email, role, hashed_token, expires_at, accepted_at |
| `integrations` | organization_id, type, display_name, public_config_json, status, config_version |
| `integration_secrets` | integration_id, encrypted_blob, nonce, key_id, updated_at |
| `projects` | organization_id, gitlab_integration_id, external_project_id, branch_config_json, enabled |
| `poll_checkpoints` | project_id, cursor_json, last_success_at, lease_owner, lease_expires_at |
| `events` | organization_id, project_id, source_event_key, event_type, state_version, facts_json, timestamps |
| `analysis_runs` | event_id, status, prompt_version, model, result_json, usage_json, error_code |
| `destinations` | organization_id nullable, user_id nullable, provider, integration_id nullable, config_json, enabled; exactly one owner scope |
| `routing_rules` | organization_id, project_id nullable, event_types_json, min_severity, destination_id, enabled |
| `jobs` | organization_id, type, payload_json, status, attempts, next_run_at, lease fields |
| `notification_outbox` | event_id, destination_id, kind, payload_json, status, next_attempt_at |
| `delivery_attempts` | outbox_id, attempted_at, outcome, http_status, sanitized_error |
| `audit_logs` | organization_id nullable, actor_user_id nullable, action, resource, metadata_json, timestamp |

Add database constraints ensuring owner-scope consistency and uniqueness. Where database foreign keys cannot enforce cross-table tenant matching, service validation and tests MUST enforce it. Retention defaults should be configurable (e.g. sanitized log excerpts 30 days, events/reports 90 days, audit 180 days); no retention policy may delete undelivered outbox entries without an explicit terminal-state rule.

## 8. API surface (v1)

Prefix `/api/v1`; JSON requests/responses; OpenAPI generated by FastAPI; error envelope includes stable `code`, `message`, `request_id`.

| Area | Representative endpoints |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/change-password` |
| Organizations | `GET/POST /organizations`, `GET/PATCH /organizations/{id}`, `POST /organizations/{id}/invitations` |
| Memberships/teams | `GET /organizations/{id}/members`, `PATCH /organizations/{id}/members/{userId}`, CRUD `/organizations/{id}/teams` |
| Integrations | CRUD `/organizations/{id}/integrations`, `POST /integrations/{id}/test`, `PUT /integrations/{id}/secret` |
| Projects | CRUD `/organizations/{id}/projects`, `POST /projects/{id}/poll-now` |
| Destinations | CRUD `/organizations/{id}/destinations`, CRUD `/users/me/destinations`, `POST /destinations/{id}/test` |
| Routing | CRUD `/organizations/{id}/routing-rules` |
| Reports | `GET /organizations/{id}/events`, `GET /events/{id}`, `GET /events/{id}/analyses`, `POST /events/{id}/reanalyze` |
| Deliveries | `GET /organizations/{id}/deliveries`, `POST /deliveries/{id}/retry` |
| Health | `GET /health/live`, `GET /health/ready`, authenticated `GET /admin/health` |

Write-only secret update payloads MUST be excluded from response serialization and logging. Mutating endpoints require CSRF protection and role checks. Pagination, bounded filters and sorting are required for list endpoints.

## 9. Release intelligence rules

### 9.1 Event classifications

- `PIPELINE_FAILED`, `PIPELINE_RECOVERED`, `MR_OPENED`, `MR_UPDATED`, `MR_MERGED`, `STAGING_CHANGED`, `RELEASE_CANDIDATE_CHANGED`, `PRODUCTION_DEPLOYMENT_FAILED` (only when trusted deployment status is available).
- Severity is deterministic by policy: default `info` for summaries, `warning` for staging failure, `critical` for verified production deployment failure. AI must not silently escalate to critical without supporting facts and rule approval.

### 9.2 Evidence requirements

- Every claim about a pipeline or commit references GitLab project, pipeline/job/MR ID and URL where available.
- Comparisons specify exact source and target SHA, not just branch names.
- Release candidate assessment includes `ci_status`, `release_composition`, `qa_approval_status`, `unknowns`, `suggested_actions`.
- QA approval status defaults to `unknown`; green pipeline means CI passed, not QA approval.
- The AI should be allowed to answer “insufficient evidence.”

### 9.3 AI execution safety and budgets

- Configurable per-org model, daily budget, max input/output tokens, concurrency and timeout.
- Cache analysis by event identity + evidence hash + prompt version + model where safe.
- Redact token-like strings, Authorization headers, cookies, private keys, and known secrets from fetched logs before model calls; store only sanitized excerpts.
- If budget exhausted or model unavailable, deliver deterministic factual notification and show `analysis_unavailable`.
- Model output is data, never an instruction to run shell commands or alter infrastructure.

## 10. UI specification

### 10.1 Layout

- Left navigation: Overview, Projects, Activity, Investigations, Notifications, Integrations, Organization, Settings.
- Top bar: organization switcher, user menu, worker health indicator.
- Overview: monitoring health, active failures, latest release candidate, recent notifications.
- Project detail: branch mappings, last poll, pipeline status, MR changes, latest analyses.
- Integration detail: masked secret state, last tested timestamp, rotate action, health.
- Notification settings: provider destination form, routing rules, test send, history.
- Investigation detail: facts, AI hypotheses, evidence links, uncertainties, usage and model metadata.

### 10.2 UX constraints

- Mobile-responsive browser interface, desktop-first.
- Sensitive actions require confirmation; credential updates display immediate validation feedback.
- Never show raw secret after save; input placeholder must not imply the secret is retrievable.
- All async operations show loading, success and actionable error states.
- Accessibility: semantic labels, keyboard focus, readable contrast, screen-reader announcements for critical state changes.

## 11. Deployment and operations

### 11.1 Docker Compose (reference)

- Services: PostgreSQL, FastAPI, worker, static web frontend/reverse proxy.
- Named volume for database; separate operator-managed secret injection; no credentials baked into images.
- Health checks, restart policies, graceful shutdown, DB migrations run as explicit deployment step.
- Bind dashboard to loopback by default; publish remotely only behind HTTPS and configured allowed origins.

### 11.2 Local Mac and Linux service

- Provide scripts to install a launchd user/system agent (macOS) or systemd unit (Linux) for API and worker; configurable data/log paths.
- App runs with no browser open. User visits `http://127.0.0.1:<port>` locally; for remote access use HTTPS reverse proxy/VPN.
- Package initial releases as source/uv-based installation plus Docker; standalone signed binaries/installers are later work, not a promise for MVP.
- Document start, stop, restart, update, backup, restore, master-key handling, and credential rotation.

### 11.3 Operational failure handling

- DB unavailable: fail readiness, retry connection, do not silently drop events.
- GitLab unavailable/rate limited: backoff, retain cursor, surface degraded status.
- AI unavailable: factual fallback alert.
- Discord unavailable: Pushover delivery proceeds independently.
- Credential revoked: integration marked unhealthy and authorized admins alerted through remaining working destinations when possible.
- Worker crashes: leases expire; jobs retry idempotently.

## 12. Testing and quality gates

- **Unit:** permission policies, branch comparison logic, event deduplication, routing, provider formatting, secret versioning, AI schema parsing.
- **Integration:** PostgreSQL transactions, worker leasing, outbox retries, GitLab mocked API pagination/rate limits, credential rotation without restart, invitation/session flows.
- **Security:** cross-org IDOR attempts, CSRF, session expiry, SSRF allowlist, secret redaction, prompt injection in logs/MR text, unauthorized config changes.
- **End-to-end:** browser onboarding, project registration, destination setup, simulated pipeline failure, Discord/Pushover mocked delivery, service restart recovery.
- **Contract:** provider interface compliance and OpenAPI client generation checks.
- **CI:** Python lint/format/type checks (`ruff`, `mypy` or `pyright`), `pytest`; TypeScript strict checks, ESLint, Vitest; Playwright smoke tests.
- All external APIs mocked in default CI; opt-in live integration tests only with dedicated test accounts and explicit credentials.

## 13. MVP acceptance criteria

1. Fresh operator can install on a Mac or VPS following README, and worker runs without browser/public URL.
2. Two users can join one organization; a user in another organization cannot access its projects, analyses, destinations or integrations.
3. Admin connects GitLab and monitors a project with custom branch mappings.
4. A simulated new failed Stage pipeline produces one persisted event, one structured analysis or factual fallback, and one notification per matching destination.
5. Repeated polls and worker restarts do not create duplicate logical events/outbox entries.
6. Discord/Pushover credentials can be rotated while worker runs; next delivery uses replacement without restart; no plaintext secret appears in API response/logs.
7. Discord outage does not prevent Pushover delivery; failed sends are retried and recorded.
8. Stage vs Main report identifies exact refs/commits and labels QA approval `unknown` without trusted approval data.
9. Operators can view worker heartbeat, poll status, analysis history and notification attempts.
10. Unit/integration/e2e checks pass, security-sensitive paths have negative tests, and documentation describes recovery and backups.

## 14. Implementation plan for Codex

**Rule:** Complete and verify one milestone before proceeding to the next. Each PR includes changed files, tests, migration notes, security implications, and remaining gaps. Do not claim an integration works unless exercised against a mock or authorized test environment.

### Milestone 0 — Repository scaffolding

- Create monorepo, backend/frontend tooling, Docker Compose, formatting/lint/type/test pipelines, `.env.example`, README.
- Add architectural decision records for tenancy, polling, secrets and queue design.
- **Done when:** one command starts web/API/worker/DB; health/readiness endpoints, database migrations, baseline lint/type/test checks, and the frontend shell work.

### Milestone 1 — Identity and organizations

- Implement DB migrations, user/session/invitation/org/membership/team models and authorization policies.
- Build login, organization switcher, members and teams screens.
- **Done when:** cross-org isolation and auth security tests pass. Authenticated organization creation is enabled by default, with an instance-level policy to disable unrestricted creation; public registration remains disabled by default.

### Milestone 2 — Live integration configuration

- Implement encrypted secret store, integration CRUD, versioned live rotation, audit log, GitLab/Discord/Pushover configuration forms and connection tests.
- **Done when:** GitLab and Discord credentials can be rotated under a running worker and the next operation resolves the new version without restart; rotation tests and audit records pass.

### Milestone 3 — GitLab monitoring

- Build GitLab client, project registration, polling leases/cursors, canonical event persistence, deduplication, pipeline/MR/ref collectors.
- **Done when:** fixture-driven pipeline failure and Stage/Main changes create accurate events with links; the default project polling interval is 300 seconds and persisted polling state survives restart.

### Milestone 4 — AI analysis

- Implement deterministic fact collection, sanitized evidence, OpenAI adapter, typed outputs, fallback behavior, budget limits.
- **Done when:** mocked model analysis is reproducible using runtime-selected `gpt-5-mini` by default, and an unavailable model still yields factual alerts. Future Codex-powered investigation remains an adapter boundary only; no generic agent orchestration is included.

### Milestone 5 — Notification delivery

- Implement provider registry, destinations, rules, outbox, retry worker, Discord and Pushover adapters, delivery history UI.
- **Done when:** the PostgreSQL transactional outbox creates one logical notification per event/destination, provides durable at-least-once delivery, and passes provider isolation, rotation, retry, and deduplication tests. Exactly-once external delivery is not guaranteed without provider-supported idempotency.

### Milestone 6 — Operational hardening and release

- Add health dashboard, structured logs, backup/restore docs, launchd/systemd examples, Docker production instructions, Playwright happy-path tests and security review.
- **Done when:** clean-install acceptance checklist passes on a Linux Docker host and the portable runtime remains documented for later macOS launchd support.

### Vertical-slice delivery rule

The capability groups above are implemented incrementally through small, reviewable milestones. The first end-to-end slice must reach the pipeline-failure workflow as early as practical: minimal authenticated organization/project configuration, GitLab polling, live-rotatable GitLab and Discord credentials, deterministic evidence collection, grounded OpenAI analysis, transactional-outbox delivery, and persisted delivery history. Administrative breadth and operational polish must not delay that slice. Every implemented capability must enforce organization isolation and its corresponding security controls when introduced.

### Later milestones (not MVP)

- Optional GitLab webhook transport, Codex deep-investigation adapter, interactive Discord bot, email provider, QA approval integration, project/team ACLs, remote agent architecture, federation/instance registry, packaged installers.

## 15. Codex operating instructions

1. Read `spec.md` completely before modifying code. Start by producing a short implementation plan for the next milestone only.
2. Follow the prescribed stack; ask before adding infrastructure dependencies (Redis, Kafka, Celery, Electron, etc.).
3. Prefer small, testable interfaces and vertical slices over speculative abstractions.
4. Keep external integrations behind adapters and use dependency injection for tests.
5. Generate and apply migrations for schema changes; never silently reset a database.
6. Never commit API keys, webhook URLs, tokens, `.env`, private keys, or unredacted production logs.
7. Never use real user credentials or send real notifications in automated tests.
8. Never grant Codex write access to monitored GitLab repositories in MVP.
9. Do not infer approvals from CI status; mark unverified states `unknown`.
10. After each milestone, report completed acceptance criteria, commands run, tests passing/failing, risks and proposed next steps.

### First Codex task (copy into Codex)

> Read `spec.md` as the authoritative product and architecture specification. Implement **Milestone 0 only**. First summarize the repository layout and key architectural decisions. Then scaffold the React/Vite frontend, FastAPI API, Python worker, PostgreSQL Docker Compose setup, health checks, lint/type/test tooling, `.env.example`, and README with local and Docker run instructions. Keep all secrets out of source control. Do not implement authentication, GitLab integration, AI analysis, or notifications yet. Run available checks and report results and any assumptions.

## 16. Open questions (non-blocking defaults)

- **Organization invitations:** MVP uses expiring shareable links; email invitations follow when email provider exists.
- **GitLab provider:** GitLab.com and self-managed GitLab supported via configurable URL and explicit endpoint allowlist.
- **AI billing:** each organization can configure its own OpenAI credential; an instance-provided credential is deferred to avoid cross-tenant billing confusion.
- **Personal vs org alerts:** personal destinations receive only events the user can access, with opt-in rules; org destinations configured by admin.
- **Teams:** organizational grouping only in MVP; per-team project permissions are deferred.
- **Public signup:** disabled by default; bootstrap + invites.
- **Standalone installer:** initial distribution is Docker or source installation; native executable packaging later.
- **Delivery semantics:** notification delivery is durable and at-least-once through the PostgreSQL transactional outbox; exactly-once delivery to external providers cannot be guaranteed without provider-supported idempotency.
- **Agent scope:** MVP uses deterministic monitoring plus an OpenAI adapter. Codex-powered investigations may be added behind an adapter later; generic autonomous agent orchestration is out of scope.
- **GitLab safety:** MVP access is read-only. Release Guardian never automatically merges, deploys, rolls back, or modifies repository code.

## 17. Definition of done

MVP is complete only when all acceptance criteria in §13 pass, docs support a fresh Mac/VPS installation, runtime provider secret rotation is verified without restart, tenant isolation has negative tests, event delivery survives restarts, and no release report confuses AI hypotheses with verified facts.
