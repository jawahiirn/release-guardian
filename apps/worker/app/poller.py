"""PostgreSQL-backed, read-only GitLab polling for monitored projects."""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import Engine, text

from apps.worker.app.analyzer import enqueue_analysis_job
from apps.worker.app.delivery import enqueue_event_notifications
from packages.crypto import SecretCipher
from packages.gitlab import GitLabClient, GitLabClientError
from packages.monitoring import pipeline_event, polling_delay_seconds, release_composition_event

logger = logging.getLogger(__name__)


class PollingClient(Protocol):
    def recent_pipelines(self, external_project_id: str) -> list[dict[str, Any]]: ...

    def pipeline_jobs(self, external_project_id: str, pipeline_id: str) -> list[dict[str, Any]]: ...

    def branch(self, external_project_id: str, ref: str) -> dict[str, Any]: ...

    def compare_refs(
        self, external_project_id: str, *, from_ref: str, to_ref: str
    ) -> dict[str, Any]: ...


ClientFactory = Callable[[str, str], PollingClient]


def default_client_factory(base_url: str, token: str) -> PollingClient:
    return GitLabClient(base_url, token)


def poll_due_projects(
    engine: Engine,
    worker_name: str,
    *,
    client_factory: ClientFactory = default_client_factory,
    now: datetime | None = None,
    jitter_seconds: int | None = None,
) -> int:
    """Claim and poll due projects; return the number of newly persisted events."""

    observed_at = now or datetime.now(UTC)
    with engine.connect() as connection:
        projects = (
            connection.execute(
                text(
                    """
                    SELECT p.id, p.organization_id, p.external_project_id, p.name,
                           p.branch_config_json AS branch_config,
                           p.polling_interval_seconds, c.retry_count, c.last_poll_at,
                           i.public_config_json AS integration_config,
                           s.encrypted_blob, s.nonce, s.key_id
                    FROM projects p
                    JOIN integrations i ON i.id = p.gitlab_integration_id
                    JOIN integration_secrets s ON s.integration_id = i.id
                    JOIN poll_checkpoints c ON c.project_id = p.id
                    WHERE p.enabled
                      AND (c.next_poll_at IS NULL OR c.next_poll_at <= now())
                      AND (c.lease_expires_at IS NULL OR c.lease_expires_at < now())
                    ORDER BY c.next_poll_at NULLS FIRST
                    """
                )
            )
            .mappings()
            .all()
        )

    events_created = 0
    for project in projects:
        if not _claim_project(engine, str(project["id"]), worker_name):
            continue
        try:
            cipher = SecretCipher()
            token = cipher.decrypt(project["encrypted_blob"], project["nonce"], project["key_id"])
            base_url = str(project["integration_config"].get("base_url", "https://gitlab.com"))
            client = client_factory(base_url, token)
            new_event_ids = _poll_project(
                engine,
                project,
                client,
                observed_at=observed_at,
                jitter_seconds=jitter_seconds,
            )
            events_created += len(new_event_ids)
        except Exception as exc:  # noqa: BLE001 - a project failure must not stop other projects
            _record_poll_failure(engine, project, observed_at, exc)
            logger.warning("GitLab poll failed for project %s", project["id"])
    return events_created


def _claim_project(engine: Engine, project_id: str, worker_name: str) -> bool:
    with engine.begin() as connection:
        claimed = connection.execute(
            text(
                """
                UPDATE poll_checkpoints
                SET lease_owner = :worker_name, lease_expires_at = now() + interval '60 seconds'
                WHERE project_id = :project_id
                  AND (next_poll_at IS NULL OR next_poll_at <= now())
                  AND (lease_expires_at IS NULL OR lease_expires_at < now())
                RETURNING project_id
                """
            ),
            {"project_id": project_id, "worker_name": worker_name},
        ).scalar_one_or_none()
    return claimed is not None


def _poll_project(
    engine: Engine,
    project: Any,
    client: PollingClient,
    *,
    observed_at: datetime,
    jitter_seconds: int | None,
) -> list[str]:
    project_data = {
        "branch_config": project["branch_config"],
        "last_poll_at": project["last_poll_at"],
    }
    pipelines = client.recent_pipelines(str(project["external_project_id"]))
    composition_event: dict[str, Any] | None = None
    composition_error: str | None = None
    production_ref = str(project["branch_config"].get("production", ""))
    staging_ref = str(project["branch_config"].get("staging", ""))
    if production_ref and staging_ref:
        try:
            production_branch = client.branch(
                str(project["external_project_id"]), production_ref
            )
            staging_branch = client.branch(str(project["external_project_id"]), staging_ref)
            comparison = client.compare_refs(
                str(project["external_project_id"]),
                from_ref=production_ref,
                to_ref=staging_ref,
            )
            staging_pipeline = next(
                (
                    pipeline
                    for pipeline in pipelines
                    if str(pipeline.get("ref", "")).casefold() == staging_ref.casefold()
                ),
                None,
            )
            composition_event = release_composition_event(
                project_data,
                production_branch,
                staging_branch,
                comparison,
                ci_status=(
                    str(staging_pipeline.get("status", "unknown"))
                    if staging_pipeline
                    else "unknown"
                ),
                observed_at=observed_at,
            )
        except GitLabClientError as exc:
            composition_error = f"release comparison unavailable: {exc}"[:500]
    event_ids: list[str] = []
    with engine.begin() as connection:
        events: list[dict[str, Any]] = []
        for pipeline in pipelines[:20]:
            pipeline_id = str(pipeline.get("id", ""))
            jobs = (
                client.pipeline_jobs(str(project["external_project_id"]), pipeline_id)
                if str(pipeline.get("status", "")).lower() == "failed"
                else []
            )
            event = pipeline_event(project_data, pipeline, jobs, observed_at=observed_at)
            if event is not None:
                events.append(event)
        if composition_event is not None:
            events.append(composition_event)
        for event in events:
            inserted = connection.execute(
                text(
                    """
                    INSERT INTO events (
                        organization_id, project_id, source, source_event_key, event_type,
                        meaningful_state_version, occurred_at, observed_at, facts_json
                    ) VALUES (
                        :organization_id, :project_id, :source, :source_event_key, :event_type,
                        :meaningful_state_version, :occurred_at, :observed_at, CAST(:facts AS jsonb)
                    )
                    ON CONFLICT (
                        source, project_id, source_event_key, event_type,
                        meaningful_state_version
                    )
                    DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    "organization_id": project["organization_id"],
                    "project_id": project["id"],
                    "source": event["source"],
                    "source_event_key": event["source_event_key"],
                    "event_type": event["event_type"],
                    "meaningful_state_version": event["meaningful_state_version"],
                    "occurred_at": event["occurred_at"],
                    "observed_at": event["observed_at"],
                    "facts": json.dumps(event["facts"]),
                },
            ).scalar_one_or_none()
            if inserted is not None:
                event_id = str(inserted)
                if event["event_type"] != "pipeline.started":
                    enqueue_analysis_job(
                        connection, event_id, str(project["organization_id"])
                    )
                enqueue_event_notifications(
                    connection, event_id, str(project["organization_id"])
                )
                event_ids.append(event_id)
        interval = int(project["polling_interval_seconds"])
        jitter = jitter_seconds if jitter_seconds is not None else max(1, interval // 10)
        next_poll_at = observed_at + timedelta(seconds=polling_delay_seconds(interval, 0, jitter))
        connection.execute(
            text(
                """
                UPDATE poll_checkpoints
                SET last_poll_at = :last_poll_at, last_success_at = :last_success_at,
                    next_poll_at = :next_poll_at, last_error = :last_error, retry_count = 0,
                    lease_owner = NULL, lease_expires_at = NULL
                WHERE project_id = :project_id
                """
            ),
            {
                "last_poll_at": observed_at,
                "last_success_at": observed_at,
                "next_poll_at": next_poll_at,
                "last_error": composition_error,
                "project_id": project["id"],
            },
        )
    return event_ids


def _record_poll_failure(
    engine: Engine, project: Any, observed_at: datetime, error: Exception
) -> None:
    retry_count = int(project["retry_count"]) + 1
    interval = int(project["polling_interval_seconds"])
    next_poll_at = observed_at + timedelta(seconds=polling_delay_seconds(interval, retry_count))
    if isinstance(error, GitLabClientError):
        safe_error = str(error)
    else:
        safe_error = "poll failed"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE poll_checkpoints
                SET last_poll_at = :last_poll_at, next_poll_at = :next_poll_at,
                    last_error = :last_error, retry_count = :retry_count,
                    lease_owner = NULL, lease_expires_at = NULL
                WHERE project_id = :project_id
                """
            ),
            {
                "last_poll_at": observed_at,
                "next_poll_at": next_poll_at,
                "last_error": safe_error[:500],
                "retry_count": retry_count,
                "project_id": project["id"],
            },
        )
