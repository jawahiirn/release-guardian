"""Add versioned event analyses."""

from alembic import op

revision = "0005_event_analyses"
down_revision = "0004_projects_polling_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analyses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            status TEXT NOT NULL CHECK (status IN ('complete', 'fallback')),
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            evidence_hash TEXT NOT NULL,
            analysis_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_code TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (event_id, evidence_hash, prompt_version, model)
        );
        CREATE INDEX IF NOT EXISTS analyses_organization_created_idx
            ON analyses(organization_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS analyses_event_created_idx
            ON analyses(event_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS analyses")
