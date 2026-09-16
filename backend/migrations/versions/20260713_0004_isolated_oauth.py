"""Add isolated Baidu OAuth state and token metadata."""

from alembic import op


revision = "20260713_0004"
down_revision = "20260713_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE platform_core.authorization_tokens
            ADD COLUMN IF NOT EXISTS user_id bigint;
        ALTER TABLE platform_core.authorization_tokens
            ADD COLUMN IF NOT EXISTS open_id varchar(240);
        ALTER TABLE platform_core.authorization_tokens
            ADD COLUMN IF NOT EXISTS refresh_expires_at timestamptz;
        CREATE TABLE IF NOT EXISTS platform_core.oauth_states (
            state_hash varchar(64) PRIMARY KEY,
            context jsonb NOT NULL DEFAULT '{}'::jsonb,
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform_core.oauth_states")
    op.execute(
        """
        ALTER TABLE platform_core.authorization_tokens
            DROP COLUMN IF EXISTS refresh_expires_at;
        ALTER TABLE platform_core.authorization_tokens
            DROP COLUMN IF EXISTS open_id;
        ALTER TABLE platform_core.authorization_tokens
            DROP COLUMN IF EXISTS user_id;
        """
    )
