import json
from io import BytesIO
from urllib.error import HTTPError

from packages.notifications import (
    DiscordWebhookProvider,
    PushoverProvider,
    format_pipeline_failure,
    format_pushover_message,
)


class FakeResponse:
    status = 204

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b""


def test_discord_provider_posts_bounded_content_without_mentions() -> None:
    requests: list[tuple[object, float]] = []

    def fake_request(request, *, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    status = DiscordWebhookProvider(timeout_seconds=3.5, request_fn=fake_request).send(
        "https://discord.com/api/webhooks/example", "pipeline failed"
    )

    assert status == 204
    request = requests[0][0]
    assert requests[0][1] == 3.5
    assert "wait=true" in request.full_url
    assert request.headers["User-agent"] == "ReleaseGuardian/0.1"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["content"] == "pipeline failed"
    assert payload["allowed_mentions"] == {"parse": []}


def test_pipeline_failure_message_includes_only_safe_gitlab_link() -> None:
    message = format_pipeline_failure(
        {
            "project_name": "Example project",
            "facts": {
                "pipeline_id": "42",
                "ref": "Stage",
                "sha": "abc123",
                "web_url": "https://gitlab.com/example/project/-/pipelines/42",
            }
        },
        {"summary": "Investigate the failed job."},
    )
    embed = message["embeds"][0]
    assert embed["title"] == "Pipeline failed · Stage"
    assert embed["url"].startswith("https://gitlab.com")
    assert any(field["name"] == "AI analysis" for field in embed["fields"])


def test_success_message_uses_green_embed_and_pipeline_link() -> None:
    message = format_pipeline_failure(
        {
            "project_name": "Example project",
            "facts": {
                "pipeline_id": "42",
                "status": "success",
                "ref": "stage",
                "sha": "abcdef1234567890",
                "web_url": "https://gitlab.com/example/project/-/pipelines/42",
            },
        },
        {"summary": "Pipeline completed successfully."},
    )
    embed = message["embeds"][0]
    assert embed["title"] == "Pipeline succeeded · stage"
    assert embed["color"] == 0x2ECC71
    assert embed["description"] == (
        "**Example project**\n"
        "**Pipeline:** [#42](https://gitlab.com/example/project/-/pipelines/42)"
    )
    assert "abcdef" not in str(embed)


def test_discord_provider_surfaces_sanitized_provider_error() -> None:
    def fake_request(request, *, timeout):
        raise HTTPError(
            request.full_url,
            403,
            "Forbidden",
            {},
            BytesIO(b'{"message":"Missing Permissions","code":50013}'),
        )

    try:
        DiscordWebhookProvider(request_fn=fake_request).send(
            "https://discord.com/api/webhooks/example", "test"
        )
    except Exception as exc:  # noqa: BLE001 - assert the public provider error
        assert "Missing Permissions" in str(exc)
        assert "50013" in str(exc)
    else:
        raise AssertionError("expected Discord delivery to fail")


def test_pushover_provider_posts_form_encoded_credentials_without_logging_them() -> None:
    requests: list[tuple[object, float]] = []

    def fake_request(request, *, timeout):
        requests.append((request, timeout))
        return FakeResponse()

    status = PushoverProvider(timeout_seconds=2.5, request_fn=fake_request).send(
        {"token": "app-token", "user_key": "user-key"},
        "Pipeline failed",
        "Review the failed job.",
    )

    assert status == 204
    request = requests[0][0]
    assert request.full_url == "https://api.pushover.net/1/messages.json"
    assert requests[0][1] == 2.5
    assert request.headers["Content-type"] == "application/x-www-form-urlencoded"
    assert b"token=app-token" in request.data
    assert b"user=user-key" in request.data


def test_pushover_message_is_bounded_and_keeps_analysis_advisory() -> None:
    title, message = format_pushover_message(
        {
            "project_name": "Example",
            "facts": {"pipeline_id": "42", "status": "failed", "ref": "Stage"},
        },
        {"summary": "Likely test failure; verify the job logs."},
    )

    assert title == "Pipeline failed · Stage"
    assert "Likely test failure" in message
    assert len(message) <= 1024


def test_release_composition_notification_marks_qa_unknown() -> None:
    message = format_pipeline_failure(
        {
            "project_name": "Example",
            "facts": {
                "production_ref": "Main",
                "production_sha": "production-sha",
                "candidate_ref": "Stage",
                "candidate_sha": "candidate-sha",
                "included_commit_count": 2,
                "ci_status": "success",
            },
        },
        {"summary": "Review the candidate before promotion."},
    )

    embed = message["embeds"][0]
    assert embed["title"] == "Release candidate · Stage → Main"
    assert any(field == {"name": "QA approval", "value": "unknown"} for field in embed["fields"])
