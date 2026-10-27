"""Small read-only GitLab HTTP adapter used by the monitoring worker."""

import json
import os
from collections.abc import Callable
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


class GitLabClientError(RuntimeError):
    """Raised when a GitLab read fails or returns an unusable response."""


RequestFn = Callable[[Request, float], Any]


def allowed_gitlab_hosts() -> set[str]:
    configured = os.getenv("GITLAB_ALLOWED_HOSTS", "gitlab.com")
    return {host.strip().lower() for host in configured.split(",") if host.strip()}


def validate_gitlab_host(base_url: str, allowed_hosts: set[str] | None = None) -> None:
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not hostname:
        raise GitLabClientError("GitLab base URL must use HTTPS")
    if hostname not in (allowed_hosts or allowed_gitlab_hosts()):
        raise GitLabClientError("GitLab host is not in the configured allowlist")


class GitLabClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 10.0,
        request_fn: RequestFn | None = None,
        allowed_hosts: set[str] | None = None,
    ) -> None:
        validate_gitlab_host(base_url, allowed_hosts)
        if not token.strip():
            raise GitLabClientError("GitLab token is required")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.request_fn: RequestFn = request_fn or cast(RequestFn, urlopen)

    def _get_json(self, path: str) -> Any:
        request = Request(
            f"{self.base_url}/api/v4/{path.lstrip('/')}",
            headers={"Accept": "application/json", "PRIVATE-TOKEN": self.token},
            method="GET",
        )
        try:
            with self.request_fn(request, self.timeout_seconds) as response:
                raw = response.read(2_000_000)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise GitLabClientError("GitLab request failed") from exc
        try:
            return json.loads(raw)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitLabClientError("GitLab returned invalid JSON") from exc

    def recent_pipelines(self, external_project_id: str) -> list[dict[str, Any]]:
        project = quote(external_project_id, safe="")
        result = self._get_json(
            f"projects/{project}/pipelines?per_page=20&order_by=updated_at&sort=desc"
        )
        if not isinstance(result, list):
            raise GitLabClientError("GitLab pipelines response was not a list")
        return [item for item in result if isinstance(item, dict)]

    def pipeline_jobs(self, external_project_id: str, pipeline_id: str) -> list[dict[str, Any]]:
        project = quote(external_project_id, safe="")
        pipeline = quote(pipeline_id, safe="")
        result = self._get_json(f"projects/{project}/pipelines/{pipeline}/jobs?per_page=100")
        if not isinstance(result, list):
            raise GitLabClientError("GitLab jobs response was not a list")
        return [item for item in result if isinstance(item, dict)]
