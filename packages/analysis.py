"""Provider-neutral, evidence-grounded event analysis primitives."""

import hashlib
import json
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROMPT_VERSION = "pipeline-failure-v1"
DEFAULT_MODEL = "gpt-5-mini"
MAX_STRING_LENGTH = 2000
MAX_COLLECTION_ITEMS = 20

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(\b(token|secret|password|api[_-]?key)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----.*?-----END [A-Z ]+ PRIVATE KEY-----", re.S),
)


class ReleaseAnalysis(BaseModel):
    """The model-visible analysis contract stored as JSON."""

    model_config = ConfigDict(extra="forbid")

    severity: Literal["info", "warning", "critical"]
    summary: str = Field(min_length=1, max_length=1000)
    likely_causes: list[str] = Field(max_length=8)
    supporting_facts: list[str] = Field(max_length=12)
    unknowns: list[str] = Field(max_length=12)
    suggested_actions: list[str] = Field(max_length=12)
    confidence: Literal["low", "medium", "high"]


class AnalysisProvider(Protocol):
    def analyze(
        self, facts: dict[str, Any], *, model: str, max_output_tokens: int
    ) -> ReleaseAnalysis:
        """Return a validated analysis for sanitized facts."""


def sanitize_evidence(value: Any, *, depth: int = 0) -> Any:
    """Bound and redact untrusted provider content before model input or storage."""

    if depth > 4:
        return "[truncated]"
    if isinstance(value, str):
        sanitized = value[:MAX_STRING_LENGTH]
        for pattern in _SECRET_PATTERNS:
            sanitized = pattern.sub(
                lambda match: (
                    f"{match.group(1)}[REDACTED]" if match.lastindex else "[REDACTED]"
                ),
                sanitized,
            )
        return sanitized
    if isinstance(value, dict):
        return {
            str(key)[:100]: sanitize_evidence(item, depth=depth + 1)
            for key, item in list(value.items())[:MAX_COLLECTION_ITEMS]
        }
    if isinstance(value, list):
        return [sanitize_evidence(item, depth=depth + 1) for item in value[:MAX_COLLECTION_ITEMS]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_STRING_LENGTH]


def evidence_hash(facts: dict[str, Any]) -> str:
    canonical = json.dumps(sanitize_evidence(facts), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fallback_analysis(facts: dict[str, Any]) -> ReleaseAnalysis:
    ref = str(facts.get("ref") or "unknown ref")
    pipeline_id = str(facts.get("pipeline_id") or "unknown pipeline")
    sha = str(facts.get("sha") or "unknown SHA")
    evidence = facts.get("failure_evidence")
    if not isinstance(evidence, list):
        evidence = []
    failed_jobs = [
        str(item.get("name"))
        for item in evidence
        if isinstance(item, dict) and item.get("name")
    ]
    supporting = [f"Pipeline {pipeline_id} failed for ref {ref} at commit {sha}."]
    if failed_jobs:
        supporting.append("Failed jobs: " + ", ".join(failed_jobs[:8]))
    return ReleaseAnalysis(
        severity="warning",
        summary=f"Pipeline {pipeline_id} failed for {ref}; the root cause requires investigation.",
        likely_causes=[],
        supporting_facts=supporting,
        unknowns=["No model analysis is available for this event."],
        suggested_actions=["Open the GitLab pipeline and failed job links for investigation."],
        confidence="low",
    )


def analysis_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
            "summary": {"type": "string"},
            "likely_causes": {"type": "array", "items": {"type": "string"}},
            "supporting_facts": {"type": "array", "items": {"type": "string"}},
            "unknowns": {"type": "array", "items": {"type": "string"}},
            "suggested_actions": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": [
            "severity",
            "summary",
            "likely_causes",
            "supporting_facts",
            "unknowns",
            "suggested_actions",
            "confidence",
        ],
    }


def validate_model_output(payload: Any) -> ReleaseAnalysis:
    try:
        return ReleaseAnalysis.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("model output did not match the analysis schema") from exc
