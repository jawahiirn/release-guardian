"""Add monitored projects, polling checkpoints, and canonical events."""

from alembic import op

revision = "0004_projects_polling_events"
down_revision = "0003_integrations_and_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            gitlab_integration_id UUID NOT NULL REFERENCES integrations(id) ON DELETE RESTRICT,
            external_project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            branch_config_json JSONB NOT NULL DEFAULT
                '{"development":"Develop","staging":"Stage","production":"Main"}'::jsonb,
            polling_interval_seconds INTEGER NOT NULL DEFAULT 300
                CHECK (polling_interval_seconds BETWEEN 30 AND 86400),
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (gitlab_integration_id, external_project_id)
        );
        CREATE INDEX IF NOT EXISTS projects_organization_id_idx ON projects(organization_id);
        CREATE TABLE IF NOT EXISTS poll_checkpoints (
            project_id UUID PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
            cursor_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            last_poll_at TIMESTAMPTZ,
            last_success_at TIMESTAMPTZ,
            next_poll_at TIMESTAMPTZ,
            last_error TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            lease_owner TEXT,
            lease_expires_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS poll_checkpoints_due_idx
            ON poll_checkpoints(next_poll_at, lease_expires_at);
        CREATE TABLE IF NOT EXISTS events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            source TEXT NOT NULL,
            source_event_key TEXT NOT NULL,
            event_type TEXT NOT NULL,
            meaningful_state_version TEXT NOT NULL,
            occurred_at TIMESTAMPTZ,
            observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            payload_version INTEGER NOT NULL DEFAULT 1,
            facts_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (source, project_id, source_event_key, event_type, meaningful_state_version)
        );
        CREATE INDEX IF NOT EXISTS events_organization_observed_idx
            ON events(organization_id, observed_at DESC);
        CREATE INDEX IF NOT EXISTS events_project_observed_idx
            ON events(project_id, observed_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS events")
    op.execute("DROP TABLE IF EXISTS poll_checkpoints")
    op.execute("DROP TABLE IF EXISTS projects")
