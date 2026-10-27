"""Add notification destinations, transactional outbox, and delivery attempts."""

from alembic import op

revision = "0006_notification_delivery"
down_revision = "0005_event_analyses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS destinations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            integration_id UUID NOT NULL UNIQUE REFERENCES integrations(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('discord', 'pushover')),
            display_name TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS destinations_organization_idx
            ON destinations(organization_id, created_at DESC);

        INSERT INTO destinations (organization_id, integration_id, kind, display_name)
        SELECT organization_id, id, type, display_name
        FROM integrations
        WHERE type = 'discord'
        ON CONFLICT (integration_id) DO NOTHING;

        CREATE TABLE IF NOT EXISTS notification_outbox (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            destination_id UUID NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'in_progress', 'delivered', 'failed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            lease_owner TEXT,
            lease_expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (event_id, destination_id, kind)
        );
        CREATE INDEX IF NOT EXISTS notification_outbox_due_idx
            ON notification_outbox(status, next_attempt_at, lease_expires_at);
        CREATE INDEX IF NOT EXISTS notification_outbox_organization_idx
            ON notification_outbox(organization_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS delivery_attempts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            outbox_id UUID NOT NULL REFERENCES notification_outbox(id) ON DELETE CASCADE,
            attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            outcome TEXT NOT NULL CHECK (outcome IN ('delivered', 'retry', 'failed')),
            http_status INTEGER,
            sanitized_error TEXT
        );
        CREATE INDEX IF NOT EXISTS delivery_attempts_outbox_idx
            ON delivery_attempts(outbox_id, attempted_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS delivery_attempts")
    op.execute("DROP TABLE IF EXISTS notification_outbox")
    op.execute("DROP TABLE IF EXISTS destinations")
