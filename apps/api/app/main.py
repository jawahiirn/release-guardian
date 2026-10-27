import os
import re
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import create_engine, text

from packages.security import hash_token, new_token, session_expiry, verify_password

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://release_guardian:change-me-in-local-env@localhost:5432/release_guardian",
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

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
    ],
)
SESSION_COOKIE = "release_guardian_session"
CSRF_HEADER = "X-CSRF-Token"


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
    return [dict(row) for row in rows]


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
    return {**dict(organization), "role": "owner"}
