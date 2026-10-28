"""Deterministic monitoring transformations shared by the worker and tests."""

from datetime import UTC, datetime
from typing import Any

DEFAULT_BRANCH_CONFIG = {
    "development": "Develop",
    "staging": "Stage",
    "production": "Main",
}
ACTIVE_PIPELINE_STATUSES = {
    "created",
    "waiting_for_resource",
    "preparing",
    "pending",
    "running",
}


def failed_pipeline_event(
    project: dict[str, Any],
    pipeline: dict[str, Any],
    jobs: list[dict[str, Any]],
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Convert a failed tracked pipeline into a bounded canonical event payload."""

    event = pipeline_event(project, pipeline, jobs, observed_at=observed_at)
    return event if event and event["event_type"] == "pipeline.failed" else None


def pipeline_event(
    project: dict[str, Any],
    pipeline: dict[str, Any],
    jobs: list[dict[str, Any]],
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Convert a tracked pipeline state into a canonical event."""

    pipeline_status = str(pipeline.get("status", "")).lower()
    if pipeline_status not in {"failed", "success", *ACTIVE_PIPELINE_STATUSES}:
        return None
    branch_config = project.get("branch_config", DEFAULT_BRANCH_CONFIG)
    tracked_branches = {str(value).casefold() for value in branch_config.values() if value}
    ref = str(pipeline.get("ref", ""))
    source = str(pipeline.get("source", "")).lower()
    is_merge_request = source == "merge_request_event" or ref.startswith(
        "refs/merge-requests/"
    )
    if is_merge_request:
        last_poll_at = project.get("last_poll_at")
        pipeline_updated_at = _parse_timestamp(
            pipeline.get("updated_at") or pipeline.get("created_at")
        )
        if (
            last_poll_at is not None
            and pipeline_updated_at is not None
            and pipeline_updated_at <= last_poll_at
        ):
            return None
    elif ref.casefold() not in tracked_branches:
        return None
    pipeline_id = str(pipeline.get("id", ""))
    sha = str(pipeline.get("sha", ""))
    if not pipeline_id or not sha:
        return None
    evidence = [
        {
            "id": str(job.get("id", "")),
            "name": str(job.get("name", "")),
            "stage": str(job.get("stage", "")),
            "status": str(job.get("status", "")),
            "failure_reason": str(job.get("failure_reason", "")),
            "web_url": str(job.get("web_url", "")),
        }
        for job in jobs
        if pipeline_status == "failed" and str(job.get("status", "")).lower() == "failed"
    ][:20]
    occurred_at = _parse_timestamp(pipeline.get("updated_at") or pipeline.get("created_at"))
    event_type = (
        "pipeline.started"
        if pipeline_status in ACTIVE_PIPELINE_STATUSES
        else f"pipeline.{pipeline_status}"
    )
    meaningful_status = "started" if event_type == "pipeline.started" else pipeline_status
    return {
        "source": "gitlab",
        "source_event_key": f"pipeline:{pipeline_id}",
        "event_type": event_type,
        "meaningful_state_version": f"{sha}:{meaningful_status}",
        "occurred_at": occurred_at,
        "observed_at": observed_at or datetime.now(UTC),
        "facts": {
            "pipeline_id": pipeline_id,
            "status": pipeline_status,
            "ref": ref,
            "merge_request_iid": (
                ref.split("/")[2]
                if is_merge_request
                and len(ref.split("/")) > 3
                and ref.split("/")[2].isdigit()
                else None
            ),
            "sha": sha,
            "web_url": str(pipeline.get("web_url", "")),
            "failure_evidence": evidence,
        },
    }


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def polling_delay_seconds(interval_seconds: int, retry_count: int, jitter_seconds: int = 0) -> int:
    backoff_multiplier = 2 ** min(max(retry_count, 0), 5)
    return min(interval_seconds * backoff_multiplier, 3600) + max(jitter_seconds, 0)
