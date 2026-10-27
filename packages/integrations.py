"""Provider-neutral configuration validation for integration settings."""

import json
from urllib.parse import urlparse


class IntegrationConfigError(ValueError):
    """Raised when an integration's public configuration or secret is invalid."""


def _require_non_empty_secret(secret: str | None) -> str:
    if not secret or not secret.strip():
        raise IntegrationConfigError("integration secret is required")
    return secret.strip()


def _validate_http_url(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntegrationConfigError(f"{field_name} must be an absolute URL")
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise IntegrationConfigError(f"{field_name} must use http or https")
    if parsed.username or parsed.password:
        raise IntegrationConfigError(f"{field_name} must not contain credentials")
    return value.strip().rstrip("/")


def validate_integration_config(
    integration_type: str,
    public_config: dict[str, object],
    secret: str | None = None,
) -> None:
    """Validate provider shape without making a network request or logging secrets."""

    if integration_type == "gitlab":
        _validate_http_url(public_config.get("base_url", "https://gitlab.com"), "base_url")
        if secret is not None:
            _require_non_empty_secret(secret)
        return

    if integration_type == "openai":
        model = public_config.get("model", "gpt-5-mini")
        if not isinstance(model, str) or not model.strip() or len(model) > 120:
            raise IntegrationConfigError("model must be a non-empty string")
        if secret is not None:
            _require_non_empty_secret(secret)
        return

    if integration_type == "discord":
        if secret is not None:
            webhook_url = _require_non_empty_secret(secret)
            parsed = urlparse(webhook_url)
            if parsed.scheme != "https" or parsed.hostname not in {
                "discord.com",
                "discordapp.com",
            }:
                raise IntegrationConfigError("Discord secret must be a Discord HTTPS webhook URL")
        return

    if integration_type == "pushover":
        if secret is not None:
            try:
                parsed_secret = json.loads(_require_non_empty_secret(secret))
            except json.JSONDecodeError as exc:
                raise IntegrationConfigError("Pushover secret must be JSON credentials") from exc
            if (
                not isinstance(parsed_secret, dict)
                or not parsed_secret.get("token")
                or not parsed_secret.get("user_key")
            ):
                raise IntegrationConfigError("Pushover secret requires token and user_key")
        return

    raise IntegrationConfigError("unsupported integration type")
