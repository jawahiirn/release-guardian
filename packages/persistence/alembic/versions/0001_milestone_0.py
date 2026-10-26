"""Create Milestone 0 operational tables."""

from alembic import op

revision = "0001_milestone_0"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_heartbeats (
            worker_name TEXT PRIMARY KEY,
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS worker_heartbeats")
    op.execute("DROP TABLE IF EXISTS schema_metadata")
