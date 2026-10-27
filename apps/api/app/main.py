import json
import os
import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import create_engine, text

from packages.crypto import SecretCipher
from packages.integrations import IntegrationConfigError, validate_integration_config
from packages.security import hash_token, new_token, session_expiry, verify_password

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://release_guardian:change-me-in-local-env@localhost:5432/release_guardian",
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SESSION_COOKIE = "release_guardian_session"
CSRF_HEADER = "X-CSRF-Token"

app = FastAPI(
    title="Release Guardian API",
    summary="Advisory release monitoring and notification API",
    description=(
        "The Release Guardian MVP observes release activity, preserves objective facts, "
        "and provides advisory analysis. GitLab access is read-only during the MVP."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {"name": "health", "description": "Service liveness and readiness checks."},
        {"name": "auth", "description": "Session-based authentication and identity."},
        {
            "name": "organizations",
            "description": "Authenticated organization membership and creation.",
        },
        {
            "name": "integrations",
            "description": "Organization-scoped provider configuration and secret rotation.",
        },
        {
            "name": "projects",
            "description": "Organization-scoped GitLab monitoring projects and polling state.",
        },
        {
            "name": "events",
            "description": "Organization-scoped observed GitLab events.",
        },
    ],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", CSRF_HEADER],
)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)


class OrganizationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class HealthResponse(BaseModel):
    status: str
    checked_at: str | None = None


class LoginResponse(BaseModel):
    email: EmailStr
    csrf_token: str


class MeResponse(BaseModel):
    id: str
    email: EmailStr


class OrganizationResponse(BaseModel):
    id: str
    name: str
    slug: str
    role: str


class IntegrationCreate(BaseModel):
    type: Literal["gitlab", "openai", "discord", "pushover"]
    display_name: str = Field(min_length=1, max_length=120)
    public_config: dict[str, object] = Field(default_factory=dict)


class IntegrationSecretUpdate(BaseModel):
    secret: str = Field(min_length=1, max_length=10000)


class IntegrationResponse(BaseModel):
    id: str
    organization_id: str
    type: str
    display_name: str
    public_config: dict[str, object]
    status: str
    config_version: int
    has_secret: bool
    secret_updated_at: datetime | None = None


class IntegrationTestResponse(BaseModel):
    status: Literal["passed"]
    live_check: bool
    message: str


class ProjectCreate(BaseModel):
    gitlab_integration_id: UUID
    external_project_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=160)
    branch_config: dict[str, str] = Field(
        default_factory=lambda: {
            "development": "Develop",
            "staging": "Stage",
            "production": "Main",
        }
    )
    polling_interval_seconds: int = Field(default=300, ge=30, le=86400)
    enabled: bool = True


class ProjectResponse(BaseModel):
    id: str
    organization_id: str
    gitlab_integration_id: str
    external_project_id: str
    name: str
    branch_config: dict[str, str]
    polling_interval_seconds: int
    enabled: bool
    last_poll_at: datetime | None = None
    last_success_at: datetime | None = None
    next_poll_at: datetime | None = None
    last_error: str | None = None


class PollNowResponse(BaseModel):
    project_id: str
    status: Literal["scheduled"]


class EventResponse(BaseModel):
    id: str
    organization_id: str
    project_id: str
    source: str
    event_type: str
    meaningful_state_version: str
    occurred_at: datetime | None = None
    observed_at: datetime
    facts: dict[str, object]


def require_org_admin(connection, organization_id: str, user_id: str) -> None:
    membership = connection.execute(
        text(
            "SELECT role FROM memberships "
            "WHERE organization_id = :organization_id AND user_id = :user_id"
        ),
        {"organization_id": organization_id, "user_id": user_id},
    ).scalar_one_or_none()
    if membership not in {"owner", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="organization admin required"
        )


def require_org_member(connection, organization_id: str, user_id: str) -> None:
    membership = connection.execute(
        text(
            "SELECT 1 FROM memberships "
            "WHERE organization_id = :organization_id AND user_id = :user_id"
        ),
        {"organization_id": organization_id, "user_id": user_id},
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="organization not found")


def audit(
    connection,
    organization_id: str,
    actor_user_id: str,
    action: str,
    resource: str,
    metadata: dict,
) -> None:
    connection.execute(
        text(
            "INSERT INTO audit_logs "
            "(organization_id, actor_user_id, action, resource, metadata_json) "
            "VALUES (:organization_id, :actor_user_id, :action, :resource, "
            "CAST(:metadata AS jsonb))"
        ),
        {
            "organization_id": organization_id,
            "actor_user_id": actor_user_id,
            "action": action,
            "resource": resource,
            "metadata": json.dumps(metadata),
        },
    )


def current_session(
    session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> dict:
    if not session_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    with engine.begin() as connection:
        row = (
            connection.execute(
                text(
                    """
                SELECT s.id, s.user_id, s.csrf_token_hash, s.expires_at, u.email
                FROM sessions s JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = :token_hash AND s.revoked_at IS NULL AND s.expires_at > now()
                """
                ),
                {"token_hash": hash_token(session_cookie)},
            )
            .mappings()
            .first()
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
    return dict(row)


def require_csrf(
    session: Annotated[dict, Depends(current_session)],
    csrf_token: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
) -> dict:
    if not csrf_token or hash_token(csrf_token) != session["csrf_token_hash"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid csrf token")
    return session


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "organization"


@app.get(
    "/health/live",
    response_model=HealthResponse,
    response_model_exclude_none=True,
    tags=["health"],
    summary="Check API liveness",
)
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/health/ready",
    response_model=HealthResponse,
    response_model_exclude_none=True,
    tags=["health"],
    summary="Check API readiness",
)
def ready() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ready", "checked_at": datetime.now(UTC).isoformat()}


@app.post(
    "/api/v1/auth/login",
    response_model=LoginResponse,
    tags=["auth"],
    summary="Create an authenticated session",
)
def login(payload: LoginRequest, response: Response) -> dict[str, str]:
    with engine.begin() as connection:
        user = (
            connection.execute(
                text(
                    "SELECT id, email, password_hash FROM users "
                    "WHERE lower(email) = lower(:email) AND status = 'active'"
                ),
                {"email": str(payload.email)},
            )
            .mappings()
            .first()
        )
        if user is None or not verify_password(user["password_hash"], payload.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
            )
        raw_session = new_token()
        csrf_token = new_token()
        connection.execute(
            text(
                """
                INSERT INTO sessions (user_id, token_hash, csrf_token_hash, expires_at)
                VALUES (:user_id, :token_hash, :csrf_token_hash, :expires_at)
                """
            ),
            {
                "user_id": user["id"],
                "token_hash": hash_token(raw_session),
                "csrf_token_hash": hash_token(csrf_token),
                "expires_at": session_expiry(),
            },
        )
    response.set_cookie(
        SESSION_COOKIE,
        raw_session,
        httponly=True,
        secure=os.getenv("APP_ENV") == "production",
        samesite="lax",
        max_age=43200,
    )
    return {"email": user["email"], "csrf_token": csrf_token}


@app.post(
    "/api/v1/auth/logout", status_code=204, tags=["auth"], summary="Revoke the current session"
)
def logout(response: Response, session: Annotated[dict, Depends(require_csrf)]) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE sessions SET revoked_at = now() WHERE id = :id"), {"id": session["id"]}
        )
    response.delete_cookie(SESSION_COOKIE)


@app.get(
    "/api/v1/auth/me", response_model=MeResponse, tags=["auth"], summary="Get the current user"
)
def me(session: Annotated[dict, Depends(current_session)]) -> dict[str, str]:
    return {"id": str(session["user_id"]), "email": session["email"]}


@app.get(
    "/api/v1/organizations",
    response_model=list[OrganizationResponse],
    tags=["organizations"],
    summary="List organizations for the current user",
)
def list_organizations(session: Annotated[dict, Depends(current_session)]) -> list[dict]:
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    """
                SELECT o.id, o.name, o.slug, m.role
                FROM organizations o JOIN memberships m ON m.organization_id = o.id
                WHERE m.user_id = :user_id ORDER BY o.name
                """
                ),
                {"user_id": session["user_id"]},
            )
            .mappings()
            .all()
        )
    return [{**dict(row), "id": str(row["id"])} for row in rows]


@app.post(
    "/api/v1/organizations",
    response_model=OrganizationResponse,
    status_code=201,
    tags=["organizations"],
    summary="Create an organization",
)
def create_organization(
    payload: OrganizationRequest, session: Annotated[dict, Depends(require_csrf)]
) -> dict:
    slug = slugify(payload.name)
    with engine.begin() as connection:
        existing = connection.execute(
            text("SELECT 1 FROM organizations WHERE slug = :slug"), {"slug": slug}
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="organization slug already exists")
        organization = (
            connection.execute(
                text(
                    "INSERT INTO organizations (name, slug, owner_id) "
                    "VALUES (:name, :slug, :owner_id) RETURNING id, name, slug"
                ),
                {"name": payload.name.strip(), "slug": slug, "owner_id": session["user_id"]},
            )
            .mappings()
            .one()
        )
        connection.execute(
            text(
                "INSERT INTO memberships (organization_id, user_id, role) "
                "VALUES (:organization_id, :user_id, 'owner')"
            ),
            {"organization_id": organization["id"], "user_id": session["user_id"]},
        )
    return {**dict(organization), "id": str(organization["id"]), "role": "owner"}


@app.get(
    "/api/v1/organizations/{organization_id}/integrations",
    response_model=list[IntegrationResponse],
    tags=["integrations"],
    summary="List organization integrations without secrets",
)
def list_integrations(
    organization_id: str, session: Annotated[dict, Depends(current_session)]
) -> list[dict]:
    with engine.connect() as connection:
        require_org_member(connection, organization_id, str(session["user_id"]))
        rows = (
            connection.execute(
                text(
                    """
                    SELECT i.id, i.organization_id, i.type, i.display_name,
                           i.public_config_json AS public_config, i.status,
                           i.config_version, s.integration_id IS NOT NULL AS has_secret,
                           s.updated_at AS secret_updated_at
                    FROM integrations i
                    JOIN memberships m ON m.organization_id = i.organization_id
                    LEFT JOIN integration_secrets s ON s.integration_id = i.id
                    WHERE i.organization_id = :organization_id AND m.user_id = :user_id
                    ORDER BY i.display_name
                    """
                ),
                {"organization_id": organization_id, "user_id": session["user_id"]},
            )
            .mappings()
            .all()
        )
    return [
        {
            **dict(row),
            "id": str(row["id"]),
            "organization_id": str(row["organization_id"]),
        }
        for row in rows
    ]


@app.post(
    "/api/v1/organizations/{organization_id}/integrations",
    response_model=IntegrationResponse,
    status_code=201,
    tags=["integrations"],
    summary="Create an integration configuration",
)
def create_integration(
    organization_id: str,
    payload: IntegrationCreate,
    session: Annotated[dict, Depends(require_csrf)],
) -> dict:
    try:
        validate_integration_config(payload.type, payload.public_config)
    except IntegrationConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    with engine.begin() as connection:
        require_org_admin(connection, organization_id, str(session["user_id"]))
        integration = (
            connection.execute(
                text(
                    "INSERT INTO integrations "
                    "(organization_id, type, display_name, public_config_json) "
                    "VALUES (:organization_id, :type, :display_name, "
                    "CAST(:public_config AS jsonb)) "
                    "RETURNING id, organization_id, type, display_name, "
                    "public_config_json AS public_config, "
                    "status, config_version"
                ),
                {
                    "organization_id": organization_id,
                    "type": payload.type,
                    "display_name": payload.display_name.strip(),
                    "public_config": json.dumps(payload.public_config),
                },
            )
            .mappings()
            .one()
        )
        audit(
            connection,
            organization_id,
            str(session["user_id"]),
            "integration.created",
            str(integration["id"]),
            {"type": payload.type, "display_name": payload.display_name.strip()},
        )
    return {
        **dict(integration),
        "id": str(integration["id"]),
        "organization_id": str(integration["organization_id"]),
        "has_secret": False,
        "secret_updated_at": None,
    }


@app.put(
    "/api/v1/integrations/{integration_id}/secret",
    response_model=IntegrationResponse,
    tags=["integrations"],
    summary="Replace an integration secret without restarting services",
)
def rotate_integration_secret(
    integration_id: UUID,
    payload: IntegrationSecretUpdate,
    session: Annotated[dict, Depends(require_csrf)],
) -> dict:
    cipher = SecretCipher()
    encrypted_blob, nonce, key_id = cipher.encrypt(payload.secret)
    integration_key = str(integration_id)
    with engine.begin() as connection:
        integration = (
            connection.execute(
                text(
                    "SELECT id, organization_id, type, display_name, "
                    "public_config_json AS public_config, "
                    "status, config_version FROM integrations WHERE id = :integration_id"
                ),
                {"integration_id": integration_key},
            )
            .mappings()
            .first()
        )
        if integration is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="integration not found"
            )
        require_org_admin(connection, str(integration["organization_id"]), str(session["user_id"]))
        try:
            validate_integration_config(
                str(integration["type"]), integration["public_config"], payload.secret
            )
        except IntegrationConfigError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        connection.execute(
            text(
                """
                INSERT INTO integration_secrets (integration_id, encrypted_blob, nonce, key_id)
                VALUES (:integration_id, :encrypted_blob, :nonce, :key_id)
                ON CONFLICT (integration_id) DO UPDATE SET
                    encrypted_blob = EXCLUDED.encrypted_blob,
                    nonce = EXCLUDED.nonce,
                    key_id = EXCLUDED.key_id,
                    updated_at = now()
                """
            ),
            {
                "integration_id": integration_key,
                "encrypted_blob": encrypted_blob,
                "nonce": nonce,
                "key_id": key_id,
            },
        )
        updated = (
            connection.execute(
                text(
                    "UPDATE integrations SET config_version = config_version + 1, "
                    "status = 'configured', updated_at = now() "
                    "WHERE id = :integration_id RETURNING id, organization_id, type, display_name, "
                    "public_config_json AS public_config, status, config_version"
                ),
                {"integration_id": integration_key},
            )
            .mappings()
            .one()
        )
        audit(
            connection,
            str(integration["organization_id"]),
            str(session["user_id"]),
            "integration.secret_rotated",
            integration_key,
            {
                "type": integration["type"],
                "key_id": key_id,
                "config_version": updated["config_version"],
            },
        )
        secret_updated_at: datetime = connection.execute(
            text(
                "SELECT updated_at FROM integration_secrets WHERE integration_id = :integration_id"
            ),
            {"integration_id": integration_key},
        ).scalar_one()
    return {
        **dict(updated),
        "id": str(updated["id"]),
        "organization_id": str(updated["organization_id"]),
        "has_secret": True,
        "secret_updated_at": secret_updated_at,
    }


@app.post(
    "/api/v1/integrations/{integration_id}/test",
    response_model=IntegrationTestResponse,
    tags=["integrations"],
    summary="Validate a stored integration configuration without contacting its provider",
)
def test_integration(
    integration_id: UUID, session: Annotated[dict, Depends(require_csrf)]
) -> dict[str, object]:
    cipher = SecretCipher()
    integration_key = str(integration_id)
    with engine.connect() as connection:
        integration = (
            connection.execute(
                text(
                    "SELECT id, organization_id, type, public_config_json AS public_config "
                    "FROM integrations WHERE id = :integration_id"
                ),
                {"integration_id": integration_key},
            )
            .mappings()
            .first()
        )
        if integration is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="integration not found"
            )
        require_org_admin(connection, str(integration["organization_id"]), str(session["user_id"]))
        secret_row = (
            connection.execute(
                text(
                    "SELECT encrypted_blob, nonce, key_id FROM integration_secrets "
                    "WHERE integration_id = :integration_id"
                ),
                {"integration_id": integration_key},
            )
            .mappings()
            .first()
        )
        if secret_row is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="integration secret is not configured",
            )
        secret = cipher.decrypt(
            secret_row["encrypted_blob"], secret_row["nonce"], secret_row["key_id"]
        )
        try:
            validate_integration_config(
                str(integration["type"]), integration["public_config"], secret
            )
        except IntegrationConfigError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
    return {
        "status": "passed",
        "live_check": False,
        "message": "Configuration and encrypted secret validated; no provider request was made.",
    }


@app.get(
    "/api/v1/organizations/{organization_id}/projects",
    response_model=list[ProjectResponse],
    tags=["projects"],
    summary="List monitored GitLab projects for an organization",
)
def list_projects(
    organization_id: str, session: Annotated[dict, Depends(current_session)]
) -> list[dict]:
    with engine.connect() as connection:
        require_org_member(connection, organization_id, str(session["user_id"]))
        rows = (
            connection.execute(
                text(
                    """
                    SELECT p.id, p.organization_id, p.gitlab_integration_id,
                           p.external_project_id, p.name,
                           p.branch_config_json AS branch_config,
                           p.polling_interval_seconds, p.enabled,
                           c.last_poll_at, c.last_success_at, c.next_poll_at, c.last_error
                    FROM projects p
                    JOIN memberships m ON m.organization_id = p.organization_id
                    JOIN poll_checkpoints c ON c.project_id = p.id
                    WHERE p.organization_id = :organization_id AND m.user_id = :user_id
                    ORDER BY p.name
                    """
                ),
                {"organization_id": organization_id, "user_id": session["user_id"]},
            )
            .mappings()
            .all()
        )
    return [
        {
            **dict(row),
            "id": str(row["id"]),
            "organization_id": str(row["organization_id"]),
            "gitlab_integration_id": str(row["gitlab_integration_id"]),
        }
        for row in rows
    ]


@app.post(
    "/api/v1/organizations/{organization_id}/projects",
    response_model=ProjectResponse,
    status_code=201,
    tags=["projects"],
    summary="Register a GitLab project for monitoring",
)
def create_project(
    organization_id: str,
    payload: ProjectCreate,
    session: Annotated[dict, Depends(require_csrf)],
) -> dict:
    with engine.begin() as connection:
        require_org_admin(connection, organization_id, str(session["user_id"]))
        integration = connection.execute(
            text(
                "SELECT id FROM integrations "
                "WHERE id = :integration_id AND organization_id = :organization_id "
                "AND type = 'gitlab'"
            ),
            {
                "integration_id": str(payload.gitlab_integration_id),
                "organization_id": organization_id,
            },
        ).scalar_one_or_none()
        if integration is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="GitLab integration not found",
            )
        project = (
            connection.execute(
                text(
                    """
                    INSERT INTO projects (
                        organization_id, gitlab_integration_id, external_project_id, name,
                        branch_config_json, polling_interval_seconds, enabled
                    ) VALUES (
                        :organization_id, :gitlab_integration_id, :external_project_id, :name,
                        CAST(:branch_config AS jsonb), :polling_interval_seconds, :enabled
                    )
                    RETURNING id, organization_id, gitlab_integration_id, external_project_id,
                              name, branch_config_json AS branch_config,
                              polling_interval_seconds, enabled
                    """
                ),
                {
                    "organization_id": organization_id,
                    "gitlab_integration_id": str(payload.gitlab_integration_id),
                    "external_project_id": payload.external_project_id.strip(),
                    "name": payload.name.strip(),
                    "branch_config": json.dumps(payload.branch_config),
                    "polling_interval_seconds": payload.polling_interval_seconds,
                    "enabled": payload.enabled,
                },
            )
            .mappings()
            .one()
        )
        connection.execute(
            text("INSERT INTO poll_checkpoints (project_id) VALUES (:project_id)"),
            {"project_id": project["id"]},
        )
        audit(
            connection,
            organization_id,
            str(session["user_id"]),
            "project.created",
            str(project["id"]),
            {"external_project_id": payload.external_project_id.strip()},
        )
    return {
        **dict(project),
        "id": str(project["id"]),
        "organization_id": str(project["organization_id"]),
        "gitlab_integration_id": str(project["gitlab_integration_id"]),
    }


@app.post(
    "/api/v1/projects/{project_id}/poll-now",
    response_model=PollNowResponse,
    tags=["projects"],
    summary="Schedule an immediate project poll",
)
def poll_now(project_id: UUID, session: Annotated[dict, Depends(require_csrf)]) -> dict[str, str]:
    project_key = str(project_id)
    with engine.begin() as connection:
        organization_id = connection.execute(
            text("SELECT organization_id FROM projects WHERE id = :project_id"),
            {"project_id": project_key},
        ).scalar_one_or_none()
        if organization_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
        require_org_admin(connection, str(organization_id), str(session["user_id"]))
        connection.execute(
            text(
                "UPDATE poll_checkpoints SET next_poll_at = now(), last_error = NULL "
                "WHERE project_id = :project_id"
            ),
            {"project_id": project_key},
        )
        audit(
            connection,
            str(organization_id),
            str(session["user_id"]),
            "project.poll_scheduled",
            project_key,
            {},
        )
    return {"project_id": project_key, "status": "scheduled"}


@app.get(
    "/api/v1/organizations/{organization_id}/events",
    response_model=list[EventResponse],
    tags=["events"],
    summary="List observed events for an organization",
)
def list_events(
    organization_id: str,
    session: Annotated[dict, Depends(current_session)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    with engine.connect() as connection:
        require_org_member(connection, organization_id, str(session["user_id"]))
        rows = (
            connection.execute(
                text(
                    """
                    SELECT id, organization_id, project_id, source, event_type,
                           meaningful_state_version, occurred_at, observed_at,
                           facts_json AS facts
                    FROM events
                    WHERE organization_id = :organization_id
                    ORDER BY observed_at DESC
                    LIMIT :limit
                    """
                ),
                {"organization_id": organization_id, "limit": limit},
            )
            .mappings()
            .all()
        )
    return [
        {
            **dict(row),
            "id": str(row["id"]),
            "organization_id": str(row["organization_id"]),
            "project_id": str(row["project_id"]),
        }
        for row in rows
    ]
