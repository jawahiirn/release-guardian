import json

import pytest

from packages.gitlab import GitLabClient, GitLabClientError, validate_gitlab_host


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = json.dumps(payload).encode()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, _: int) -> bytes:
        return self.payload


def test_gitlab_client_uses_read_only_api_requests() -> None:
    requests = []

    def request_fn(request, timeout):
        requests.append((request, timeout))
        return FakeResponse([{"id": 7, "status": "failed"}])

    client = GitLabClient("https://gitlab.com", "test-token", request_fn=request_fn)
    assert client.recent_pipelines("group/project") == [{"id": 7, "status": "failed"}]
    assert requests[0][0].method == "GET"
    assert "/api/v4/projects/group%2Fproject/pipelines" in requests[0][0].full_url


def test_gitlab_host_allowlist_rejects_unsafe_or_unapproved_hosts() -> None:
    with pytest.raises(GitLabClientError):
        validate_gitlab_host("http://gitlab.com")
    with pytest.raises(GitLabClientError):
        validate_gitlab_host("https://gitlab.internal", {"gitlab.com"})
