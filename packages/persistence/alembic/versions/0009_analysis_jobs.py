"""Add durable PostgreSQL analysis jobs."""

from alembic import op

revision = "0009_analysis_jobs"
down_revision = "0008_invitations_teams"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            event_id UUID REFERENCES events(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('analyze_event')),
            state TEXT NOT NULL DEFAULT 'queued'
                CHECK (state IN ('queued', 'leased', 'succeeded', 'retryable_failed', 'dead')),
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            lease_owner TEXT,
            lease_expires_at TIMESTAMPTZ,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (kind, event_id)
        );
        CREATE INDEX IF NOT EXISTS jobs_due_idx
            ON jobs(state, next_attempt_at, lease_expires_at);

        INSERT INTO jobs (organization_id, event_id, kind)
        SELECT e.organization_id, e.id, 'analyze_event'
        FROM events e
        WHERE e.event_type <> 'pipeline.started'
          AND NOT EXISTS (SELECT 1 FROM analyses a WHERE a.event_id = e.id)
        ON CONFLICT (kind, event_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jobs")
