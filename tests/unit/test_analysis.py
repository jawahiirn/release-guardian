import json

from packages.analysis import evidence_hash, fallback_analysis, sanitize_evidence
from packages.openai_provider import OpenAIAnalysisProvider


def test_sanitize_evidence_redacts_secrets_and_bounds_content() -> None:
    value = sanitize_evidence(
        {
            "message": "Authorization: Bearer top-secret-token",
            "nested": {"token": "abc123"},
            "large": "x" * 3000,
        }
    )
    assert "top-secret-token" not in json.dumps(value)
    assert "[REDACTED]" in json.dumps(value)
    assert len(value["large"]) == 2000
    assert evidence_hash(value) == evidence_hash(value)


def test_fallback_analysis_is_factual_and_advisory() -> None:
    analysis = fallback_analysis(
        {
            "pipeline_id": "42",
            "ref": "Stage",
            "sha": "abc123",
            "failure_evidence": [{"name": "unit-tests"}],
        }
    )
    assert analysis.severity == "warning"
    assert "42" in analysis.summary
    assert analysis.confidence == "low"
    assert analysis.likely_causes == []


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_openai_provider_sends_structured_response_request() -> None:
    requests: list[tuple[object, float]] = []

    def fake_request(request, *, timeout):
        requests.append((request, timeout))
        return FakeResponse(
            {
                "output_text": json.dumps(
                    {
                        "severity": "warning",
                        "summary": "The stage pipeline failed.",
                        "likely_causes": ["unit test failure"],
                        "supporting_facts": ["pipeline 42 failed"],
                        "unknowns": ["root cause requires logs"],
                        "suggested_actions": ["inspect the failed job"],
                        "confidence": "medium",
                    }
                )
            }
        )

    analysis = OpenAIAnalysisProvider(
        "test-key", timeout_seconds=4.0, request_fn=fake_request
    ).analyze({"message": "safe"}, model="gpt-5-mini", max_output_tokens=500)

    request = requests[0][0]
    assert requests[0][1] == 4.0
    assert request.full_url.endswith("/v1/responses")
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["model"] == "gpt-5-mini"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert analysis.summary == "The stage pipeline failed."
