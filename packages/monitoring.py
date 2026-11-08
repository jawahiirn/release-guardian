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


def release_composition_event(
    project: dict[str, Any],
    production_branch: dict[str, Any],
    staging_branch: dict[str, Any],
    comparison: dict[str, Any],
    *,
    ci_status: str = "unknown",
    observed_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Build a bounded Stage-vs-Main composition event with explicit unknown QA state."""

    production_ref = str(project.get("branch_config", DEFAULT_BRANCH_CONFIG).get("production", ""))
    staging_ref = str(project.get("branch_config", DEFAULT_BRANCH_CONFIG).get("staging", ""))
    production_commit = production_branch.get("commit")
    staging_commit = staging_branch.get("commit")
    if not isinstance(production_commit, dict) or not isinstance(staging_commit, dict):
        return None
    production_sha = str(production_commit.get("id", ""))
    candidate_sha = str(staging_commit.get("id", ""))
    if not production_ref or not staging_ref or not production_sha or not candidate_sha:
        return None
    raw_commits = comparison.get("commits")
    commits = raw_commits if isinstance(raw_commits, list) else []
    included_commits = [
        {
            "sha": str(commit.get("id", "")),
            "short_sha": str(commit.get("short_id", "")),
            "title": str(commit.get("title", ""))[:500],
            "created_at": str(commit.get("created_at", "")),
            "web_url": str(commit.get("web_url", "")),
        }
        for commit in commits[:50]
        if isinstance(commit, dict) and commit.get("id")
    ]
    raw_diffs = comparison.get("diffs")
    diffs = raw_diffs if isinstance(raw_diffs, list) else []
    changed_paths = [
        str(diff.get("new_path") or diff.get("old_path"))[:500]
        for diff in diffs[:100]
        if isinstance(diff, dict) and (diff.get("new_path") or diff.get("old_path"))
    ]
    return {
        "source": "gitlab",
        "source_event_key": f"release-composition:{production_ref}:{staging_ref}",
        "event_type": "release.composition",
        "meaningful_state_version": f"{production_sha}:{candidate_sha}",
        "occurred_at": _parse_timestamp(staging_commit.get("created_at")),
        "observed_at": observed_at or datetime.now(UTC),
        "facts": {
            "production_ref": production_ref,
            "production_sha": production_sha,
            "candidate_ref": staging_ref,
            "candidate_sha": candidate_sha,
            "included_commits": included_commits,
            "included_commit_count": len(commits),
            "changed_paths": changed_paths,
            "compare_timeout": bool(comparison.get("compare_timeout", False)),
            "compare_same_ref": bool(comparison.get("compare_same_ref", False)),
            "web_url": str(comparison.get("web_url", "")),
            "ci_status": ci_status or "unknown",
            "qa_status": "unknown",
        },
    }
