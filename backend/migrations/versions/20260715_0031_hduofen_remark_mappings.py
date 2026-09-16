"""Add project-scoped Hduofen remark account mappings."""

from alembic import op


revision = "20260715_0031"
down_revision = "20260715_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS search_marketing.hduofen_account_remark_mappings (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            remark varchar(240) NOT NULL,
            normalized_remark varchar(240) NOT NULL,
            account_id uuid NOT NULL REFERENCES search_marketing.accounts(id),
            source_file text NOT NULL,
            source_sha256 varchar(64) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_hduofen_account_remark_mapping_project_remark
                UNIQUE (project_id, normalized_remark)
        );
        CREATE INDEX IF NOT EXISTS ix_hduofen_account_remark_mappings_account
            ON search_marketing.hduofen_account_remark_mappings(project_id, account_id);
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS search_marketing.hduofen_account_remark_mappings"
    )
