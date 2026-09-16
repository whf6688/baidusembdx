"""Add project-scoped Hduofen custom-ID account mappings."""

from alembic import op


revision = "20260714_0028"
down_revision = "20260714_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS search_marketing.hduofen_account_mappings (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            custom_id varchar(120) NOT NULL,
            account_id uuid NOT NULL REFERENCES search_marketing.accounts(id),
            source_file text NOT NULL,
            source_sha256 varchar(64) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_hduofen_account_mapping_project_custom
                UNIQUE (project_id, custom_id)
        );
        CREATE INDEX IF NOT EXISTS ix_hduofen_account_mappings_account
            ON search_marketing.hduofen_account_mappings(project_id, account_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS search_marketing.hduofen_account_mappings")
