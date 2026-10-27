"""Worker-side event analysis with live OpenAI credential resolution."""

import json
import logging
import os
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Engine, text

from packages.analysis import (
    DEFAULT_MODEL,
    PROMPT_VERSION,
    ReleaseAnalysis,
    evidence_hash,
    fallback_analysis,
    sanitize_evidence,
)
from packages.crypto import SecretCipher
from packages.openai_provider import OpenAIAnalysisProvider, OpenAIProviderError

logger = logging.getLogger(__name__)


def analyze_new_event(engine: Engine, event_id: str) -> bool:
    """Analyze one newly-created event and persist either model or factual fallback data."""

    with engine.connect() as connection:
        event = connection.execute(
            text(
                """
                SELECT e.id, e.organization_id, e.facts_json AS facts,
                       i.public_config_json AS openai_config,
                       s.encrypted_blob, s.nonce, s.key_id
                FROM events e
                LEFT JOIN integrations i
                  ON i.organization_id = e.organization_id AND i.type = 'openai'
                LEFT JOIN integration_secrets s ON s.integration_id = i.id
                WHERE e.id = :event_id
                ORDER BY i.updated_at DESC NULLS LAST
                LIMIT 1
                """
            ),
            {"event_id": event_id},
        ).mappings().one_or_none()
    if event is None:
        return False

    facts = sanitize_evidence(event["facts"])
    if not isinstance(facts, dict):
        facts = {}
    current_hash = evidence_hash(facts)
    openai_config = event["openai_config"] or {}
    model = str(openai_config.get("model") or os.getenv("AI_DEFAULT_MODEL", DEFAULT_MODEL))
    if not model.strip():
        model = DEFAULT_MODEL
    if _analysis_exists(engine, event_id, current_hash, model):
        return False

    max_output_tokens = _bounded_int(
        os.getenv("AI_MAX_OUTPUT_TOKENS", "1200"), default=1200, minimum=128, maximum=4096
    )
    daily_limit = _bounded_int(
        os.getenv("AI_DAILY_ANALYSIS_LIMIT", "100"), default=100, minimum=1, maximum=10000
    )
    result: ReleaseAnalysis
    if _daily_limit_reached(engine, str(event["organization_id"]), daily_limit):
        result = fallback_analysis(facts)
        _persist_analysis(
            engine,
            event,
            result,
            current_hash,
            model,
            error_code="analysis_budget_exhausted",
        )
        return True

    error_code: str | None = None
    if event["encrypted_blob"] is None:
        result = fallback_analysis(facts)
        error_code = "analysis_unavailable"
    else:
        try:
            secret = SecretCipher().decrypt(
                event["encrypted_blob"], event["nonce"], event["key_id"]
            )
            result = OpenAIAnalysisProvider(secret).analyze(
                facts, model=model, max_output_tokens=max_output_tokens
            )
        except (OpenAIProviderError, RuntimeError, ValueError):
            result = fallback_analysis(facts)
            error_code = "analysis_unavailable"
    _persist_analysis(engine, event, result, current_hash, model, error_code=error_code)
    return True


def analyze_pending_events(engine: Engine, *, limit: int = 1) -> int:
    """Process a small bounded batch after polling and delivery remain responsive."""

    with engine.connect() as connection:
        raw_event_ids: Sequence[Any] = connection.execute(
            text(
                """
                SELECT e.id
                FROM events e
                WHERE NOT EXISTS (
                    SELECT 1 FROM analyses a WHERE a.event_id = e.id
                )
                ORDER BY e.observed_at
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).scalars().all()
        event_ids = [str(event_id) for event_id in raw_event_ids]
    completed = 0
    for event_id in event_ids:
        try:
            if analyze_new_event(engine, event_id):
                completed += 1
        except Exception:  # noqa: BLE001 - analysis must not stop polling or delivery
            logger.exception("event analysis failed for event %s", event_id)
    return completed


def _analysis_exists(engine: Engine, event_id: str, evidence_hash_value: str, model: str) -> bool:
    with engine.connect() as connection:
        return (
            connection.execute(
                text(
                    """
                    SELECT 1 FROM analyses
                    WHERE event_id = :event_id AND evidence_hash = :evidence_hash
                      AND prompt_version = :prompt_version AND model = :model
                    """
                ),
                {
                    "event_id": event_id,
                    "evidence_hash": evidence_hash_value,
                    "prompt_version": PROMPT_VERSION,
                    "model": model,
                },
            ).scalar_one_or_none()
            is not None
        )


def _daily_limit_reached(engine: Engine, organization_id: str, limit: int) -> bool:
    with engine.connect() as connection:
        count: int = int(connection.execute(
            text(
                """
                SELECT count(*) FROM analyses
                WHERE organization_id = :organization_id
                  AND created_at >= date_trunc('day', now())
                  AND status = 'complete'
                """
            ),
            {"organization_id": organization_id},
        ).scalar_one())
    return count >= limit


def _persist_analysis(
    engine: Engine,
    event: Any,
    analysis: ReleaseAnalysis,
    evidence_hash_value: str,
    model: str,
    *,
    error_code: str | None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO analyses (
                    organization_id, event_id, status, model, prompt_version, evidence_hash,
                    analysis_json, error_code
                ) VALUES (
                    :organization_id, :event_id, :status, :model, :prompt_version,
                    :evidence_hash, CAST(:analysis AS jsonb), :error_code
                )
                ON CONFLICT (event_id, evidence_hash, prompt_version, model) DO NOTHING
                """
            ),
            {
                "organization_id": event["organization_id"],
                "event_id": event["id"],
                "status": "fallback" if error_code else "complete",
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "evidence_hash": evidence_hash_value,
                "analysis": json.dumps(analysis.model_dump()),
                "error_code": error_code,
            },
        )


def _bounded_int(value: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(max(int(value), minimum), maximum)
    except ValueError:
        return default
