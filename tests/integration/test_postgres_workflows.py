import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from apps.api.app import main as api_main
from apps.worker.app.delivery import _claim_notification, enqueue_event_notifications
from packages.security import hash_password


def _seed_tenant(engine: Engine, email: str) -> tuple[str, str]:
    with engine.begin() as connection:
        user_id = str(
            connection.execute(
                text(
                    "INSERT INTO users (email, password_hash) VALUES (:email, :password_hash) "
                    "RETURNING id"
                ),
                {"email": email, "password_hash": hash_password("integration-password")},
            ).scalar_one()
        )
        organization_id = str(
            connection.execute(
                text(
                    "INSERT INTO organizations (name, slug, owner_id) "
                    "VALUES (:name, :slug, :owner_id) RETURNING id"
                ),
                {"name": email, "slug": uuid4().hex, "owner_id": user_id},
            ).scalar_one()
        )
        connection.execute(
            text(
                "INSERT INTO memberships (organization_id, user_id, role) "
                "VALUES (:organization_id, :user_id, 'owner')"
            ),
            {"organization_id": organization_id, "user_id": user_id},
        )
    return user_id, organization_id


def test_cross_organization_integration_listing_is_hidden(
    integration_engine: Engine, monkeypatch
) -> None:
    _, first_organization = _seed_tenant(
        integration_engine, f"first-{uuid4().hex}@example.com"
    )
    second_email = f"second-{uuid4().hex}@example.com"
    _seed_tenant(integration_engine, second_email)
    with integration_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO integrations (organization_id, type, display_name) "
                "VALUES (:organization_id, 'gitlab', 'Private GitLab')"
            ),
            {"organization_id": first_organization},
        )
    monkeypatch.setattr(api_main, "engine", integration_engine)
    client = TestClient(api_main.app)
    login = client.post(
        "/api/v1/auth/login",
        json={"email": second_email, "password": "integration-password"},
    )
    assert login.status_code == 200

    response = client.get(f"/api/v1/organizations/{first_organization}/integrations")

    assert response.status_code == 404
    assert response.json() == {"detail": "organization not found"}


def test_outbox_is_deduplicated_and_expired_delivery_is_reclaimed(
    integration_engine: Engine,
) -> None:
    _, organization_id = _seed_tenant(
        integration_engine, f"outbox-{uuid4().hex}@example.com"
    )
    with integration_engine.begin() as connection:
        integration_id = connection.execute(
            text(
                "INSERT INTO integrations (organization_id, type, display_name) "
                "VALUES (:organization_id, 'discord', 'Discord') RETURNING id"
            ),
            {"organization_id": organization_id},
        ).scalar_one()
        destination_id = connection.execute(
            text(
                "INSERT INTO destinations (organization_id, integration_id, kind, display_name) "
                "VALUES (:organization_id, :integration_id, 'discord', 'Discord') RETURNING id"
            ),
            {"organization_id": organization_id, "integration_id": integration_id},
        ).scalar_one()
        project_id = connection.execute(
            text(
                "INSERT INTO projects (organization_id, gitlab_integration_id, "
                "external_project_id, name) VALUES "
                "(:organization_id, :integration_id, 'group/project', 'Project') RETURNING id"
            ),
            {"organization_id": organization_id, "integration_id": integration_id},
        ).scalar_one()
        event_id = connection.execute(
            text(
                "INSERT INTO events (organization_id, project_id, source, source_event_key, "
                "event_type, meaningful_state_version) VALUES "
                "(:organization_id, :project_id, 'gitlab', 'pipeline:1', "
                "'pipeline.failed', 'sha:failed') RETURNING id"
            ),
            {"organization_id": organization_id, "project_id": project_id},
        ).scalar_one()
        assert enqueue_event_notifications(connection, str(event_id), organization_id) == 1
        assert enqueue_event_notifications(connection, str(event_id), organization_id) == 0
        connection.execute(
            text(
                "UPDATE notification_outbox SET status = 'in_progress', "
                "lease_expires_at = :expired, next_attempt_at = :expired "
                "WHERE destination_id = :destination_id"
            ),
            {
                "expired": datetime.now(UTC) - timedelta(minutes=5),
                "destination_id": destination_id,
            },
        )

    claimed = _claim_notification(integration_engine, "integration-worker", datetime.now(UTC))

    assert claimed is not None
    assert str(claimed["event_id"]) == str(event_id)
    assert claimed["attempts"] == 1


def test_integration_environment_has_a_valid_encryption_key(monkeypatch) -> None:
    encoded = base64.urlsafe_b64encode(b"i" * 32).decode("ascii")
    monkeypatch.setenv("ENCRYPTION_MASTER_KEY", encoded)
    assert len(base64.urlsafe_b64decode(encoded)) == 32
