import json

import pytest

from packages.integrations import IntegrationConfigError, validate_integration_config


def test_provider_configuration_defaults_and_validation() -> None:
    validate_integration_config("gitlab", {"base_url": "https://gitlab.com"}, "token")
    validate_integration_config("openai", {}, "api-key")
    validate_integration_config("discord", {}, "https://discord.com/api/webhooks/123/token")
    validate_integration_config("pushover", {}, json.dumps({"token": "token", "user_key": "user"}))


@pytest.mark.parametrize(
    ("integration_type", "public_config", "secret"),
    [
        ("gitlab", {"base_url": "http://user:password@gitlab.local"}, "token"),
        ("discord", {}, "https://example.com/webhook"),
        ("pushover", {}, "not-json"),
    ],
)
def test_invalid_provider_configuration_is_rejected(
    integration_type: str, public_config: dict[str, object], secret: str
) -> None:
    with pytest.raises(IntegrationConfigError):
        validate_integration_config(integration_type, public_config, secret)
