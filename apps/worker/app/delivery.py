"""Durable at-least-once notification delivery for the worker."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, text

from packages.crypto import SecretCipher
from packages.notifications import (
    DiscordWebhookProvider,
    NotificationDeliveryError,
    format_pipeline_failure,
)

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 8


def enqueue_event_notifications(connection: Any, event_id: str, organization_id: str) -> int:
    """Create one logical Discord notification per event and enabled destination."""

    inserted = connection.execute(
        text(
            """
            INSERT INTO notification_outbox (
                organization_id, event_id, destination_id, kind, payload_json
            )
            SELECT d.organization_id, CAST(:event_id AS uuid), d.id, d.kind,
                   jsonb_build_object('event_id', CAST(:event_id AS text))
            FROM destinations d
            WHERE d.organization_id = :organization_id
              AND d.kind = 'discord' AND d.enabled
            ON CONFLICT (event_id, destination_id, kind) DO NOTHING
            RETURNING id
            """
        ),
        {"event_id": event_id, "organization_id": organization_id},
    ).all()
    return len(inserted)


def deliver_due_notifications(
    engine: Engine,
    worker_name: str,
    *,
    now: datetime | None = None,
    provider: DiscordWebhookProvider | None = None,
    max_items: int = 20,
) -> int:
    delivered = 0
    for _ in range(max_items):
        outbox = _claim_notification(engine, worker_name, now or datetime.now(UTC))
        if outbox is None:
            break
        try:
            _deliver_one(engine, outbox, provider or DiscordWebhookProvider())
            _record_success(engine, outbox, now or datetime.now(UTC))
            delivered += 1
        except NotificationDeliveryError as exc:
            _record_failure(engine, outbox, exc, now or datetime.now(UTC))
        except Exception:  # noqa: BLE001 - one destination must not stop the worker
            logger.exception("notification delivery failed for outbox %s", outbox["id"])
            _record_failure(
                engine,
                outbox,
                NotificationDeliveryError("notification delivery failed"),
                now or datetime.now(UTC),
            )
    return delivered


def _claim_notification(engine: Engine, worker_name: str, now: datetime) -> dict[str, Any] | None:
    with engine.begin() as connection:
        row = (
            connection.execute(
                text(
                    """
                    WITH candidate AS (
                        SELECT id FROM notification_outbox
                        WHERE status IN ('pending', 'failed')
                          AND next_attempt_at <= :now
                          AND (lease_expires_at IS NULL OR lease_expires_at < :now)
                        ORDER BY next_attempt_at, created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE notification_outbox o
                    SET status = 'in_progress', attempts = o.attempts + 1,
                        lease_owner = :worker_name,
                        lease_expires_at = :now + interval '60 seconds',
                        updated_at = :now
                    FROM candidate
                    WHERE o.id = candidate.id
                    RETURNING o.id, o.event_id, o.destination_id, o.kind,
                              o.organization_id, o.attempts
                    """
                ),
                {"now": now, "worker_name": worker_name},
            )
            .mappings()
            .one_or_none()
        )
    return dict(row) if row else None


def _deliver_one(engine: Engine, outbox: dict[str, Any], provider: DiscordWebhookProvider) -> None:
    with engine.connect() as connection:
        destination = connection.execute(
            text(
                """
                SELECT d.kind, i.type, s.encrypted_blob, s.nonce, s.key_id,
                       e.facts_json AS facts, a.analysis_json AS analysis,
                       p.name AS project_name
                FROM destinations d
                JOIN integrations i ON i.id = d.integration_id
                LEFT JOIN integration_secrets s ON s.integration_id = i.id
                JOIN events e ON e.id = :event_id AND e.organization_id = :organization_id
                JOIN projects p ON p.id = e.project_id AND p.organization_id = e.organization_id
                LEFT JOIN LATERAL (
                    SELECT analysis_json
                    FROM analyses
                    WHERE event_id = e.id AND organization_id = e.organization_id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) a ON TRUE
                WHERE d.id = :destination_id AND d.organization_id = :organization_id
                """
            ),
            {
                "event_id": outbox["event_id"],
                "destination_id": outbox["destination_id"],
                "organization_id": outbox["organization_id"],
            },
        ).mappings().one_or_none()
    if destination is None or destination["kind"] != "discord":
        raise NotificationDeliveryError("notification destination is unavailable")
    if destination["encrypted_blob"] is None:
        raise NotificationDeliveryError("Discord destination has no credential")
    try:
        webhook_url = SecretCipher().decrypt(
            destination["encrypted_blob"], destination["nonce"], destination["key_id"]
        )
        content = format_pipeline_failure(
            {"facts": destination["facts"], "project_name": destination["project_name"]},
            destination["analysis"],
        )
        provider.send(webhook_url, content)
    except RuntimeError as exc:
        raise NotificationDeliveryError("Discord credential could not be resolved") from exc


def _record_failure(
    engine: Engine, outbox: dict[str, Any], error: NotificationDeliveryError, now: datetime
) -> None:
    attempts = int(outbox["attempts"])
    terminal = attempts >= MAX_ATTEMPTS
    next_attempt = now + timedelta(seconds=min(3600, 30 * (2 ** min(attempts - 1, 5))))
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO delivery_attempts (outbox_id, outcome, http_status, sanitized_error)
                VALUES (:outbox_id, :outcome, :http_status, :sanitized_error)
                """
            ),
            {
                "outbox_id": outbox["id"],
                "outcome": "failed" if terminal else "retry",
                "http_status": error.http_status,
                "sanitized_error": str(error)[:500],
            },
        )
        connection.execute(
            text(
                """
                UPDATE notification_outbox
                SET status = :status, next_attempt_at = :next_attempt_at,
                    lease_owner = NULL, lease_expires_at = NULL, updated_at = :updated_at
                WHERE id = :outbox_id
                """
            ),
            {
                "status": "failed" if terminal else "pending",
                "next_attempt_at": next_attempt,
                "updated_at": now,
                "outbox_id": outbox["id"],
            },
        )


def _record_success(engine: Engine, outbox: dict[str, Any], now: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO delivery_attempts (outbox_id, outcome, http_status)
                VALUES (:outbox_id, 'delivered', 204)
                """
            ),
            {"outbox_id": outbox["id"]},
        )
        connection.execute(
            text(
                """
                UPDATE notification_outbox
                SET status = 'delivered', lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = :updated_at
                WHERE id = :outbox_id
                """
            ),
            {"updated_at": now, "outbox_id": outbox["id"]},
        )

