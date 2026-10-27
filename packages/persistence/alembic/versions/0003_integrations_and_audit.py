"""Add organization integrations, encrypted secrets, and audit logs."""

from alembic import op

revision = "0003_integrations_and_audit"
down_revision = "0002_identity_organizations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS integrations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            type TEXT NOT NULL CHECK (type IN ('gitlab', 'openai', 'discord', 'pushover')),
            display_name TEXT NOT NULL,
            public_config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'unconfigured',
            config_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS integrations_organization_id_idx
            ON integrations(organization_id);
        CREATE TABLE IF NOT EXISTS integration_secrets (
            integration_id UUID PRIMARY KEY REFERENCES integrations(id) ON DELETE CASCADE,
            encrypted_blob BYTEA NOT NULL,
            nonce BYTEA NOT NULL,
            key_id TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
            actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            resource TEXT NOT NULL,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS audit_logs_organization_id_idx
            ON audit_logs(organization_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_logs")
    op.execute("DROP TABLE IF EXISTS integration_secrets")
    op.execute("DROP TABLE IF EXISTS integrations")
