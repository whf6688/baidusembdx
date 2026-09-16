"""Use transport-safe ASCII usernames for ad-build identities."""

from alembic import op


revision = "20260714_0023"
down_revision = "20260714_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE search_marketing.project_ad_build_access
           SET username = CASE operator_name
               WHEN '王康' THEN 'wang_kang'
               WHEN '王聪' THEN 'wang_cong'
               ELSE username
           END,
               updated_at = now()
         WHERE username IN ('王康', '王聪');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE search_marketing.project_ad_build_access
           SET username = operator_name,
               updated_at = now()
         WHERE username IN ('wang_kang', 'wang_cong');
        """
    )
