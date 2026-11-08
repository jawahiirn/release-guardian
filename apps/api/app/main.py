import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from packages.crypto import SecretCipher
from packages.integrations import IntegrationConfigError, validate_integration_config
from packages.notifications import DiscordWebhookProvider, NotificationDeliveryError
from packages.observability import RequestContextMiddleware, configure_json_logging
from packages.security import hash_password, hash_token, new_token, session_expiry, verify_password

configure_json_logging("api")
logger = logging.getLogger(__name__)

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
        {
            "name": "routing",
            "description": "Organization-scoped notification routing rules.",
        },
    ],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS", "http://localhost:5177,http://127.0.0.1:5177"
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", CSRF_HEADER],
)
app.add_middleware(RequestContextMiddleware)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)


class OrganizationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class HealthResponse(BaseModel):
    status: str
    checked_at: str | None = None


class HealthSnapshotResponse(BaseModel):
    status: Literal["healthy", "degraded", "critical"]
    checked_at: datetime
    database: dict[str, object]
    worker: dict[str, object]
    polling: dict[str, object]
    notifications: dict[str, object]


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


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Literal["admin", "member"] = "member"


class InvitationResponse(BaseModel):
    id: str
    organization_id: str
    email: EmailStr
    role: Literal["admin", "member"]
    expires_at: datetime
    invite_token: str


class InvitationAccept(BaseModel):
    token: str = Field(min_length=20, max_length=500)
    password: str = Field(min_length=12, max_length=256)


class MembershipResponse(BaseModel):
    user_id: str
    email: EmailStr
    role: Literal["owner", "admin", "member"]


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TeamResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    member_ids: list[str]


class TeamMemberCreate(BaseModel):
    user_id: UUID


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


class NotificationTestResponse(BaseModel):
    status: Literal["sent"]
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
    analysis_status: str | None = None
    analysis_model: str | None = None
    analysis: dict[str, object] | None = None
    analysis_created_at: datetime | None = None


class AnalysisResponse(BaseModel):
    id: str
    organization_id: str
    event_id: str
    status: Literal["complete", "fallback"]
    model: str
    prompt_version: str
    evidence_hash: str
    analysis: dict[str, object]
    error_code: str | None = None
    created_at: datetime


class DeliveryResponse(BaseModel):
    id: str
    organization_id: str
    event_id: str
    destination_id: str
    kind: str
    status: Literal["pending", "in_progress", "delivered", "failed"]
    attempts: int
    next_attempt_at: datetime
    last_attempt_at: datetime | None = None


class DeliveryRetryResponse(BaseModel):
    delivery_id: str
    status: Literal["scheduled"]


class RoutingRuleCreate(BaseModel):
    destination_id: UUID
    name: str = Field(min_length=1, max_length=120)
    event_types: list[str] = Field(default_factory=list, max_length=20)
    project_id: UUID | None = None
    enabled: bool = True


class RoutingRuleResponse(BaseModel):
    id: str
    organization_id: str
    destination_id: str
    name: str
    event_types: list[str]
    project_id: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class DestinationResponse(BaseModel):
    id: str
    organization_id: str
    kind: Literal["discord", "pushover"]
    display_name: str
    enabled: bool


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


def health_snapshot() -> dict[str, object]:
    checked_at = datetime.now(UTC)
    stale_after = int(os.getenv("WORKER_HEARTBEAT_STALE_SECONDS", "45"))
    with engine.connect() as connection:
        worker = connection.execute(
            text(
                """
                SELECT worker_name, last_seen_at,
                       extract(epoch FROM (now() - last_seen_at)) AS age_seconds
                FROM worker_heartbeats
                ORDER BY last_seen_at DESC
                LIMIT 1
                """
            )
        ).mappings().one_or_none()
        polling = connection.execute(
            text(
                """
                SELECT count(*) FILTER (WHERE p.enabled) AS enabled_projects,
                       count(*) FILTER (WHERE p.enabled AND c.last_error IS NOT NULL)
                           AS failed_projects,
                       max(c.last_poll_at) AS last_poll_at,
                       min(c.next_poll_at) FILTER (WHERE p.enabled) AS next_poll_at
                FROM projects p
                JOIN poll_checkpoints c ON c.project_id = p.id
                """
            )
        ).mappings().one()
        notifications = connection.execute(
            text(
                """
                SELECT count(*) FILTER (WHERE status = 'pending') AS pending,
                       count(*) FILTER (WHERE status = 'in_progress') AS in_progress,
                       count(*) FILTER (WHERE status = 'failed') AS failed,
                       max(updated_at) FILTER (WHERE status = 'delivered') AS last_delivered_at
                FROM notification_outbox
                """
            )
        ).mappings().one()

    worker_age = float(worker["age_seconds"]) if worker else None
    worker_status = "healthy" if worker_age is not None and worker_age <= stale_after else "stale"
    polling_status = "healthy" if int(polling["failed_projects"] or 0) == 0 else "degraded"
    notification_status = (
        "degraded" if int(notifications["failed"] or 0) > 0 else "healthy"
    )
    overall = "healthy"
    if worker_status != "healthy":
        overall = "critical"
    elif polling_status != "healthy" or notification_status != "healthy":
        overall = "degraded"
    return {
        "status": overall,
        "checked_at": checked_at,
        "database": {"status": "healthy"},
        "worker": {
            "status": worker_status,
            "worker_name": worker["worker_name"] if worker else None,
            "last_seen_at": worker["last_seen_at"] if worker else None,
            "age_seconds": round(worker_age, 1) if worker_age is not None else None,
            "stale_after_seconds": stale_after,
        },
        "polling": {
            "status": polling_status,
            "enabled_projects": int(polling["enabled_projects"] or 0),
            "failed_projects": int(polling["failed_projects"] or 0),
            "last_poll_at": polling["last_poll_at"],
            "next_poll_at": polling["next_poll_at"],
        },
        "notifications": {
            "status": notification_status,
            "pending": int(notifications["pending"] or 0),
            "in_progress": int(notifications["in_progress"] or 0),
            "failed": int(notifications["failed"] or 0),
            "last_delivered_at": notifications["last_delivered_at"],
        },
    }


@app.get(
    "/api/v1/admin/health",
    response_model=HealthSnapshotResponse,
    tags=["health"],
    summary="Read authenticated operational health",
)
@app.get(
    "/admin/health",
    response_model=HealthSnapshotResponse,
    include_in_schema=False,
)
def admin_health(session: Annotated[dict, Depends(current_session)]) -> dict[str, object]:
    del session
    try:
        return health_snapshot()
    except Exception as exc:
        logger.exception("operational health snapshot failed")
        raise HTTPException(status_code=503, detail="operational health unavailable") from exc


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
    "/api/v1/organizations/{organization_id}/members",
    response_model=list[MembershipResponse],
    tags=["organizations"],
    summary="List organization members",
)
def list_members(
    organization_id: str, session: Annotated[dict, Depends(current_session)]
) -> list[dict]:
    with engine.connect() as connection:
        require_org_member(connection, organization_id, str(session["user_id"]))
        rows = (
            connection.execute(
                text(
                    """
                    SELECT u.id AS user_id, u.email, m.role
                    FROM memberships m JOIN users u ON u.id = m.user_id
                    WHERE m.organization_id = :organization_id
                    ORDER BY u.email
                    """
                ),
                {"organization_id": organization_id},
            )
            .mappings()
            .all()
        )
    return [{**dict(row), "user_id": str(row["user_id"])} for row in rows]


@app.post(
    "/api/v1/organizations/{organization_id}/invitations",
    response_model=InvitationResponse,
    status_code=201,
    tags=["organizations"],
    summary="Create an expiring organization invitation",
)
def create_invitation(
    organization_id: str,
    payload: InvitationCreate,
    session: Annotated[dict, Depends(require_csrf)],
) -> dict:
    raw_token = new_token()
    expires_at = datetime.now(UTC) + timedelta(days=7)
    with engine.begin() as connection:
        require_org_admin(connection, organization_id, str(session["user_id"]))
        existing_member = connection.execute(
            text(
                """
                SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id
                WHERE m.organization_id = :organization_id AND lower(u.email) = lower(:email)
                """
            ),
            {"organization_id": organization_id, "email": str(payload.email)},
        ).scalar_one_or_none()
        if existing_member is not None:
            raise HTTPException(status_code=409, detail="user is already a member")
        invitation = (
            connection.execute(
                text(
                    """
                    INSERT INTO invitations (
                        organization_id, email, role, token_hash, expires_at, invited_by
                    ) VALUES (
                        :organization_id, :email, :role, :token_hash, :expires_at, :invited_by
                    )
                    RETURNING id, organization_id, email, role, expires_at
                    """
                ),
                {
                    "organization_id": organization_id,
                    "email": str(payload.email).lower(),
                    "role": payload.role,
                    "token_hash": hash_token(raw_token),
                    "expires_at": expires_at,
                    "invited_by": session["user_id"],
                },
            )
            .mappings()
            .one()
        )
        audit(
            connection,
            organization_id,
            str(session["user_id"]),
            "invitation.created",
            str(invitation["id"]),
            {"email": str(payload.email).lower(), "role": payload.role},
        )
    return {
        **dict(invitation),
        "id": str(invitation["id"]),
        "organization_id": str(invitation["organization_id"]),
        "invite_token": raw_token,
    }


@app.post(
    "/api/v1/invitations/accept",
    status_code=204,
    tags=["organizations"],
    summary="Accept an organization invitation",
)
def accept_invitation(payload: InvitationAccept) -> None:
    with engine.begin() as connection:
        invitation = (
            connection.execute(
                text(
                    """
                    SELECT id, organization_id, email, role
                    FROM invitations
                    WHERE token_hash = :token_hash AND accepted_at IS NULL
                      AND expires_at > now()
                    FOR UPDATE
                    """
                ),
                {"token_hash": hash_token(payload.token)},
            )
            .mappings()
            .one_or_none()
        )
        if invitation is None:
            raise HTTPException(status_code=404, detail="invitation not found or expired")
        user = (
            connection.execute(
                text("SELECT id, password_hash FROM users WHERE lower(email) = lower(:email)"),
                {"email": invitation["email"]},
            )
            .mappings()
            .one_or_none()
        )
        if user is None:
            user_id = connection.execute(
                text(
                    "INSERT INTO users (email, password_hash) "
                    "VALUES (:email, :password_hash) RETURNING id"
                ),
                {
                    "email": invitation["email"],
                    "password_hash": hash_password(payload.password),
                },
            ).scalar_one()
        else:
            if not verify_password(user["password_hash"], payload.password):
                raise HTTPException(status_code=401, detail="invalid credentials")
            user_id = user["id"]
        connection.execute(
            text(
                """
                INSERT INTO memberships (organization_id, user_id, role)
                VALUES (:organization_id, :user_id, :role)
                ON CONFLICT (organization_id, user_id) DO NOTHING
                """
            ),
            {
                "organization_id": invitation["organization_id"],
                "user_id": user_id,
                "role": invitation["role"],
            },
        )
        connection.execute(
            text("UPDATE invitations SET accepted_at = now() WHERE id = :invitation_id"),
            {"invitation_id": invitation["id"]},
        )
        audit(
            connection,
            str(invitation["organization_id"]),
            str(user_id),
            "invitation.accepted",
            str(invitation["id"]),
            {"role": invitation["role"]},
        )


@app.get(
    "/api/v1/organizations/{organization_id}/teams",
    response_model=list[TeamResponse],
    tags=["organizations"],
    summary="List organization teams",
)
def list_teams(
    organization_id: str, session: Annotated[dict, Depends(current_session)]
) -> list[dict]:
    with engine.connect() as connection:
        require_org_member(connection, organization_id, str(session["user_id"]))
        rows = (
            connection.execute(
                text(
                    """
                    SELECT t.id, t.organization_id, t.name,
                           COALESCE(array_agg(tm.user_id) FILTER (WHERE tm.user_id IS NOT NULL),
                                    ARRAY[]::uuid[]) AS member_ids
                    FROM teams t LEFT JOIN team_members tm ON tm.team_id = t.id
                    WHERE t.organization_id = :organization_id
                    GROUP BY t.id ORDER BY t.name
                    """
                ),
                {"organization_id": organization_id},
            )
            .mappings()
            .all()
        )
    return [
        {
            **dict(row),
            "id": str(row["id"]),
            "organization_id": str(row["organization_id"]),
            "member_ids": [str(member_id) for member_id in row["member_ids"]],
        }
        for row in rows
    ]


@app.post(
    "/api/v1/organizations/{organization_id}/teams",
    response_model=TeamResponse,
    status_code=201,
    tags=["organizations"],
    summary="Create an organization team",
)
def create_team(
    organization_id: str,
    payload: TeamCreate,
    session: Annotated[dict, Depends(require_csrf)],
) -> dict:
    with engine.begin() as connection:
        require_org_admin(connection, organization_id, str(session["user_id"]))
        try:
            team = (
                connection.execute(
                    text(
                        "INSERT INTO teams (organization_id, name) "
                        "VALUES (:organization_id, :name) "
                        "RETURNING id, organization_id, name"
                    ),
                    {"organization_id": organization_id, "name": payload.name.strip()},
                )
                .mappings()
                .one()
            )
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="team name already exists") from exc
        audit(
            connection,
            organization_id,
            str(session["user_id"]),
            "team.created",
            str(team["id"]),
            {"name": payload.name.strip()},
        )
    return {
        **dict(team),
        "id": str(team["id"]),
        "organization_id": organization_id,
        "member_ids": [],
    }


@app.post(
    "/api/v1/teams/{team_id}/members",
    status_code=204,
    tags=["organizations"],
    summary="Add an organization member to a team",
)
def add_team_member(
    team_id: UUID,
    payload: TeamMemberCreate,
    session: Annotated[dict, Depends(require_csrf)],
) -> None:
    with engine.begin() as connection:
        organization_id = connection.execute(
            text("SELECT organization_id FROM teams WHERE id = :team_id"),
            {"team_id": str(team_id)},
        ).scalar_one_or_none()
        if organization_id is None:
            raise HTTPException(status_code=404, detail="team not found")
        require_org_admin(connection, str(organization_id), str(session["user_id"]))
        membership = connection.execute(
            text(
                "SELECT 1 FROM memberships "
                "WHERE organization_id = :organization_id AND user_id = :user_id"
            ),
            {"organization_id": organization_id, "user_id": str(payload.user_id)},
        ).scalar_one_or_none()
        if membership is None:
            raise HTTPException(status_code=404, detail="organization member not found")
        connection.execute(
            text(
                "INSERT INTO team_members (team_id, user_id) VALUES (:team_id, :user_id) "
                "ON CONFLICT (team_id, user_id) DO NOTHING"
            ),
            {"team_id": str(team_id), "user_id": str(payload.user_id)},
        )


@app.delete(
    "/api/v1/teams/{team_id}",
    status_code=204,
    tags=["organizations"],
    summary="Delete an organization team",
)
def delete_team(team_id: UUID, session: Annotated[dict, Depends(require_csrf)]) -> None:
    with engine.begin() as connection:
        organization_id = connection.execute(
            text("SELECT organization_id FROM teams WHERE id = :team_id"),
            {"team_id": str(team_id)},
        ).scalar_one_or_none()
        if organization_id is None:
            raise HTTPException(status_code=404, detail="team not found")
        require_org_admin(connection, str(organization_id), str(session["user_id"]))
        connection.execute(text("DELETE FROM teams WHERE id = :team_id"), {"team_id": str(team_id)})


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
        if payload.type in {"discord", "pushover"}:
            connection.execute(
                text(
                    """
                    INSERT INTO destinations (
                        organization_id, integration_id, kind, display_name
                    ) VALUES (:organization_id, :integration_id, :kind, :display_name)
                    ON CONFLICT (integration_id) DO NOTHING
                    """
                ),
                {
                    "organization_id": organization_id,
                    "integration_id": integration["id"],
                    "kind": payload.type,
                    "display_name": payload.display_name.strip(),
                },
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


@app.post(
    "/api/v1/integrations/{integration_id}/test-notification",
    response_model=NotificationTestResponse,
    tags=["integrations"],
    summary="Send a live test notification for a Discord integration",
)
def test_notification(
    integration_id: UUID, session: Annotated[dict, Depends(require_csrf)]
) -> dict[str, object]:
    integration_key = str(integration_id)
    with engine.connect() as connection:
        integration = (
            connection.execute(
                text(
                    "SELECT id, organization_id, type FROM integrations "
                    "WHERE id = :integration_id"
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
        if integration["type"] != "discord":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="live test notifications currently support Discord only",
            )
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
    try:
        webhook_url = SecretCipher().decrypt(
            secret_row["encrypted_blob"], secret_row["nonce"], secret_row["key_id"]
        )
        http_status = DiscordWebhookProvider().send(
            webhook_url,
            "**Release Guardian test notification**\nDiscord delivery is configured correctly.",
        )
    except (NotificationDeliveryError, RuntimeError) as exc:
        detail = (
            str(exc)
            if isinstance(exc, NotificationDeliveryError)
            else "credential unavailable"
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc
    with engine.begin() as connection:
        audit(
            connection,
            str(integration["organization_id"]),
            str(session["user_id"]),
            "notification.test_sent",
            integration_key,
            {"type": "discord", "http_status": http_status},
        )
    return {
        "status": "sent",
        "live_check": True,
        "message": "Discord test notification sent.",
    }


@app.get(
    "/api/v1/organizations/{organization_id}/destinations",
    response_model=list[DestinationResponse],
    tags=["routing"],
    summary="List notification destinations",
)
def list_destinations(
    organization_id: str, session: Annotated[dict, Depends(current_session)]
) -> list[dict]:
    with engine.connect() as connection:
        require_org_member(connection, organization_id, str(session["user_id"]))
        rows = (
            connection.execute(
                text(
                    """
                    SELECT id, organization_id, kind, display_name, enabled
                    FROM destinations
                    WHERE organization_id = :organization_id
                    ORDER BY display_name
                    """
                ),
                {"organization_id": organization_id},
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


@app.get(
    "/api/v1/organizations/{organization_id}/routing-rules",
    response_model=list[RoutingRuleResponse],
    tags=["routing"],
    summary="List notification routing rules",
)
def list_routing_rules(
    organization_id: str, session: Annotated[dict, Depends(current_session)]
) -> list[dict]:
    with engine.connect() as connection:
        require_org_member(connection, organization_id, str(session["user_id"]))
        rows = (
            connection.execute(
                text(
                    """
                    SELECT id, organization_id, destination_id, name,
                           event_types_json AS event_types, project_id, enabled,
                           created_at, updated_at
                    FROM routing_rules
                    WHERE organization_id = :organization_id
                    ORDER BY created_at DESC
                    """
                ),
                {"organization_id": organization_id},
            )
            .mappings()
            .all()
        )
    return [
        {
            **dict(row),
            "id": str(row["id"]),
            "organization_id": str(row["organization_id"]),
            "destination_id": str(row["destination_id"]),
            "project_id": str(row["project_id"]) if row["project_id"] else None,
        }
        for row in rows
    ]


@app.post(
    "/api/v1/organizations/{organization_id}/routing-rules",
    response_model=RoutingRuleResponse,
    status_code=201,
    tags=["routing"],
    summary="Create a notification routing rule",
)
def create_routing_rule(
    organization_id: str,
    payload: RoutingRuleCreate,
    session: Annotated[dict, Depends(require_csrf)],
) -> dict:
    event_types = [event_type.strip() for event_type in payload.event_types if event_type.strip()]
    with engine.begin() as connection:
        require_org_admin(connection, organization_id, str(session["user_id"]))
        destination = connection.execute(
            text(
                "SELECT id FROM destinations "
                "WHERE id = :destination_id AND organization_id = :organization_id"
            ),
            {"destination_id": str(payload.destination_id), "organization_id": organization_id},
        ).scalar_one_or_none()
        if destination is None:
            raise HTTPException(status_code=404, detail="destination not found")
        if payload.project_id is not None:
            project = connection.execute(
                text(
                    "SELECT id FROM projects "
                    "WHERE id = :project_id AND organization_id = :organization_id"
                ),
                {"project_id": str(payload.project_id), "organization_id": organization_id},
            ).scalar_one_or_none()
            if project is None:
                raise HTTPException(status_code=404, detail="project not found")
        rule = (
            connection.execute(
                text(
                    """
                    INSERT INTO routing_rules (
                        organization_id, destination_id, name, event_types_json, project_id, enabled
                    ) VALUES (
                        :organization_id, :destination_id, :name,
                        CAST(:event_types AS jsonb), :project_id, :enabled
                    )
                    RETURNING id, organization_id, destination_id, name,
                              event_types_json AS event_types, project_id, enabled,
                              created_at, updated_at
                    """
                ),
                {
                    "organization_id": organization_id,
                    "destination_id": str(payload.destination_id),
                    "name": payload.name.strip(),
                    "event_types": json.dumps(event_types),
                    "project_id": str(payload.project_id) if payload.project_id else None,
                    "enabled": payload.enabled,
                },
            )
            .mappings()
            .one()
        )
        audit(
            connection,
            organization_id,
            str(session["user_id"]),
            "routing_rule.created",
            str(rule["id"]),
            {"name": payload.name.strip(), "destination_id": str(payload.destination_id)},
        )
    return {
        **dict(rule),
        "id": str(rule["id"]),
        "organization_id": str(rule["organization_id"]),
        "destination_id": str(rule["destination_id"]),
        "project_id": str(rule["project_id"]) if rule["project_id"] else None,
    }


@app.delete(
    "/api/v1/routing-rules/{rule_id}",
    status_code=204,
    tags=["routing"],
    summary="Delete a notification routing rule",
)
def delete_routing_rule(
    rule_id: UUID, session: Annotated[dict, Depends(require_csrf)]
) -> None:
    with engine.begin() as connection:
        organization_id = connection.execute(
            text("SELECT organization_id FROM routing_rules WHERE id = :rule_id"),
            {"rule_id": str(rule_id)},
        ).scalar_one_or_none()
        if organization_id is None:
            raise HTTPException(status_code=404, detail="routing rule not found")
        require_org_admin(connection, str(organization_id), str(session["user_id"]))
        connection.execute(
            text("DELETE FROM routing_rules WHERE id = :rule_id"), {"rule_id": str(rule_id)}
        )


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
        external_project_id = payload.external_project_id.strip()
        project_name = payload.name.strip()
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
        existing = connection.execute(
            text(
                """
                SELECT id, name FROM projects
                WHERE organization_id = :organization_id
                  AND gitlab_integration_id = :gitlab_integration_id
                  AND external_project_id = :external_project_id
                """
            ),
            {
                "organization_id": organization_id,
                "gitlab_integration_id": str(payload.gitlab_integration_id),
                "external_project_id": external_project_id,
            },
        ).mappings().one_or_none()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"GitLab project is already registered as '{existing['name']}'",
            )
        try:
            with connection.begin_nested():
                project = (
                    connection.execute(
                        text(
                            """
                            INSERT INTO projects (
                                organization_id, gitlab_integration_id, external_project_id, name,
                                branch_config_json, polling_interval_seconds, enabled
                            ) VALUES (
                                :organization_id, :gitlab_integration_id,
                                :external_project_id, :name,
                                CAST(:branch_config AS jsonb), :polling_interval_seconds, :enabled
                            )
                            RETURNING id, organization_id, gitlab_integration_id,
                                      external_project_id,
                                      name, branch_config_json AS branch_config,
                                      polling_interval_seconds, enabled
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "gitlab_integration_id": str(payload.gitlab_integration_id),
                            "external_project_id": external_project_id,
                            "name": project_name,
                            "branch_config": json.dumps(payload.branch_config),
                            "polling_interval_seconds": payload.polling_interval_seconds,
                            "enabled": payload.enabled,
                        },
                    )
                    .mappings()
                    .one()
                )
        except IntegrityError as exc:
            if "projects_gitlab_integration_id_external_project_id_key" in str(exc.orig):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="GitLab project is already registered for this integration",
                ) from exc
            raise
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
            {"external_project_id": external_project_id},
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
                    SELECT events.id, events.organization_id, events.project_id,
                           events.source, events.event_type,
                           events.meaningful_state_version, events.occurred_at,
                           events.observed_at, events.facts_json AS facts,
                           latest.id AS analysis_id, latest.status AS analysis_status,
                           latest.model AS analysis_model, latest.analysis_json AS analysis,
                           latest.created_at AS analysis_created_at
                    FROM events
                    LEFT JOIN LATERAL (
                        SELECT a.id, a.status, a.model, a.analysis_json, a.created_at
                        FROM analyses a
                        WHERE a.event_id = events.id
                        ORDER BY a.created_at DESC
                        LIMIT 1
                    ) latest ON TRUE
                    WHERE events.organization_id = :organization_id
                    ORDER BY events.observed_at DESC
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


@app.get(
    "/api/v1/events/{event_id}/analyses",
    response_model=list[AnalysisResponse],
    tags=["events"],
    summary="List analyses for an observed event",
)
def list_event_analyses(
    event_id: UUID, session: Annotated[dict, Depends(current_session)]
) -> list[dict]:
    with engine.connect() as connection:
        organization_id = connection.execute(
            text("SELECT organization_id FROM events WHERE id = :event_id"),
            {"event_id": str(event_id)},
        ).scalar_one_or_none()
        if organization_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="event not found")
        require_org_member(connection, str(organization_id), str(session["user_id"]))
        rows = (
            connection.execute(
                text(
                    """
                    SELECT id, organization_id, event_id, status, model, prompt_version,
                           evidence_hash, analysis_json AS analysis, error_code, created_at
                    FROM analyses
                    WHERE event_id = :event_id AND organization_id = :organization_id
                    ORDER BY created_at DESC
                    """
                ),
                {"event_id": str(event_id), "organization_id": str(organization_id)},
            )
            .mappings()
            .all()
        )
    return [
        {
            **dict(row),
            "id": str(row["id"]),
            "organization_id": str(row["organization_id"]),
            "event_id": str(row["event_id"]),
        }
        for row in rows
    ]


@app.get(
    "/api/v1/organizations/{organization_id}/deliveries",
    response_model=list[DeliveryResponse],
    tags=["deliveries"],
    summary="List notification delivery history for an organization",
)
def list_deliveries(
    organization_id: str,
    session: Annotated[dict, Depends(current_session)],
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict]:
    with engine.connect() as connection:
        require_org_member(connection, organization_id, str(session["user_id"]))
        rows = (
            connection.execute(
                text(
                    """
                    SELECT n.id, n.organization_id, n.event_id, n.destination_id,
                           n.kind, n.status, n.attempts, n.next_attempt_at,
                           max(a.attempted_at) AS last_attempt_at
                    FROM notification_outbox n
                    LEFT JOIN delivery_attempts a ON a.outbox_id = n.id
                    WHERE n.organization_id = :organization_id
                    GROUP BY n.id
                    ORDER BY n.created_at DESC
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
            "event_id": str(row["event_id"]),
            "destination_id": str(row["destination_id"]),
        }
        for row in rows
    ]


@app.post(
    "/api/v1/deliveries/{delivery_id}/retry",
    response_model=DeliveryRetryResponse,
    tags=["deliveries"],
    summary="Schedule a failed notification for retry",
)
def retry_delivery(
    delivery_id: UUID, session: Annotated[dict, Depends(require_csrf)]
) -> dict[str, str]:
    with engine.begin() as connection:
        organization_id = connection.execute(
            text("SELECT organization_id FROM notification_outbox WHERE id = :delivery_id"),
            {"delivery_id": str(delivery_id)},
        ).scalar_one_or_none()
        if organization_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="delivery not found")
        require_org_admin(connection, str(organization_id), str(session["user_id"]))
        connection.execute(
            text(
                """
                UPDATE notification_outbox
                SET status = 'pending', next_attempt_at = now(),
                    lease_owner = NULL, lease_expires_at = NULL, updated_at = now()
                WHERE id = :delivery_id AND status IN ('failed', 'pending')
                """
            ),
            {"delivery_id": str(delivery_id)},
        )
    return {"delivery_id": str(delivery_id), "status": "scheduled"}
