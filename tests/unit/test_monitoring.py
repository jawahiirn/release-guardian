from datetime import UTC, datetime

from packages.monitoring import failed_pipeline_event, pipeline_event, polling_delay_seconds


def test_failed_tracked_pipeline_becomes_bounded_event() -> None:
    project = {"branch_config": {"staging": "Stage"}}
    pipeline = {
        "id": 42,
        "status": "failed",
        "ref": "Stage",
        "sha": "abc123",
        "web_url": "https://gitlab.com/example/project/-/pipelines/42",
        "updated_at": "2026-10-27T12:00:00Z",
    }
    jobs = [
        {"id": index, "name": f"job-{index}", "status": "failed", "stage": "test"}
        for index in range(30)
    ]
    event = failed_pipeline_event(
        project,
        pipeline,
        jobs,
        observed_at=datetime(2026, 10, 27, tzinfo=UTC),
    )
    assert event is not None
    assert event["event_type"] == "pipeline.failed"
    assert event["meaningful_state_version"] == "abc123:failed"
    assert len(event["facts"]["failure_evidence"]) == 20


def test_untracked_or_non_failed_pipeline_is_ignored() -> None:
    project = {"branch_config": {"staging": "Stage"}}
    assert (
        failed_pipeline_event(
            project, {"id": 1, "status": "success", "ref": "Stage", "sha": "a"}, []
        )
        is None
    )
    assert (
        failed_pipeline_event(
            project, {"id": 2, "status": "failed", "ref": "feature", "sha": "b"}, []
        )
        is None
    )


def test_successful_tracked_pipeline_becomes_event() -> None:
    event = pipeline_event(
        {"branch_config": {"staging": "Stage"}},
        {"id": 7, "status": "success", "ref": "Stage", "sha": "def456"},
        [],
    )
    assert event is not None
    assert event["event_type"] == "pipeline.success"
    assert event["meaningful_state_version"] == "def456:success"


def test_polling_backoff_is_bounded() -> None:
    assert polling_delay_seconds(300, 0) == 300
    assert polling_delay_seconds(300, 1) == 600
    assert polling_delay_seconds(300, 10) == 3600
