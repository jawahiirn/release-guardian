"""Provider-neutral notification payloads and Discord delivery adapter."""

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class NotificationDeliveryError(RuntimeError):
    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


def _urlopen(request: Request, timeout: float) -> Any:
    return urlopen(request, timeout=timeout)


class DiscordWebhookProvider:
    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        request_fn: Callable[..., Any] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.request_fn = request_fn or _urlopen

    def send(self, webhook_url: str, content: str | dict[str, Any]) -> int:
        separator = "&" if "?" in webhook_url else "?"
        payload = (
            {"content": content[:2000], "allowed_mentions": {"parse": []}}
            if isinstance(content, str)
            else content
        )
        request = Request(
            f"{webhook_url}{separator}wait=true",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ReleaseGuardian/0.1",
            },
            method="POST",
        )
        try:
            with self.request_fn(request, timeout=self.timeout_seconds) as response:
                response.read()
                status = int(response.status)
                if status < 200 or status >= 300:
                    raise NotificationDeliveryError(
                        f"Discord webhook returned HTTP {status}", http_status=status
                    )
                return status
        except HTTPError as exc:
            detail = _discord_error_detail(exc)
            raise NotificationDeliveryError(
                f"Discord webhook returned HTTP {exc.code}: {detail}", http_status=exc.code
            ) from exc
        except (OSError, URLError, TimeoutError) as exc:
            raise NotificationDeliveryError("Discord webhook request failed") from exc


def _discord_error_detail(error: HTTPError) -> str:
    try:
        payload = json.loads(error.read(512).decode("utf-8", errors="replace"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "provider rejected the request"
    message = payload.get("message") if isinstance(payload, dict) else None
    code = payload.get("code") if isinstance(payload, dict) else None
    if isinstance(message, str) and message:
        safe_message = " ".join(message.split())[:200]
        return f"{safe_message} (Discord code {code})" if code else safe_message
    return "provider rejected the request"


def format_pipeline_failure(
    event: dict[str, Any], analysis: dict[str, Any] | None
) -> dict[str, Any]:
    raw_facts = event.get("facts")
    facts = raw_facts if isinstance(raw_facts, dict) else {}
    pipeline_id = str(facts.get("pipeline_id", "unknown"))
    ref = str(facts.get("ref", "unknown"))
    pipeline_status = str(facts.get("status", "failed"))
    is_started = pipeline_status in {
        "created",
        "waiting_for_resource",
        "preparing",
        "pending",
        "running",
    }
    status_label = (
        "started"
        if is_started
        else "succeeded" if pipeline_status == "success" else "failed"
    )
    web_url = str(facts.get("web_url", ""))
    safe_url = web_url if web_url.startswith("https://") else ""
    project_name = str(event.get("project_name") or "GitLab project")
    pipeline_reference = (
        f"[#{pipeline_id}]({safe_url})" if safe_url else f"`#{pipeline_id}`"
    )
    summary = str(analysis.get("summary", "")).strip() if analysis else ""
    analysis_label = "AI analysis" if analysis else "Factual fallback"
    evidence = facts.get("failure_evidence")
    failed_jobs = (
        [
            str(job.get("name"))
            for job in evidence
            if isinstance(job, dict) and job.get("name")
        ]
        if isinstance(evidence, list)
        else []
    )
    fields: list[dict[str, Any]] = []
    if failed_jobs:
        fields.append({"name": "Failed jobs", "value": ", ".join(failed_jobs[:8])[:1024]})
    if is_started:
        fields.append({"name": "Current state", "value": pipeline_status})
    else:
        fields.append(
            {
                "name": analysis_label,
                "value": (
                    summary or "Model analysis is unavailable; review the pipeline facts."
                )[:1024],
            }
        )
    return {
        "embeds": [
            {
                "title": f"Pipeline {status_label} · {ref}",
                "description": f"**{project_name[:200]}**\n**Pipeline:** {pipeline_reference}",
                "url": safe_url or None,
                "color": (
                    0x3498DB
                    if is_started
                    else 0x2ECC71
                    if pipeline_status == "success"
                    else 0xE74C3C
                ),
                "fields": fields,
                "footer": {"text": "Release Guardian"},
            }
        ],
        "allowed_mentions": {"parse": []},
    }
