import json
from io import BytesIO
from urllib.error import HTTPError

from packages.notifications import DiscordWebhookProvider, format_pipeline_failure


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


def test_success_message_uses_green_embed_and_short_commit() -> None:
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
    assert any(field["value"] == "`abcdef12`" for field in embed["fields"])


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
