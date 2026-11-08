"""Add organization-scoped notification routing rules."""

from alembic import op

revision = "0007_routing_rules"
down_revision = "0006_notification_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS routing_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            destination_id UUID NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            event_types_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS routing_rules_destination_idx
            ON routing_rules(destination_id, enabled);
        CREATE INDEX IF NOT EXISTS routing_rules_organization_idx
            ON routing_rules(organization_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS routing_rules")
