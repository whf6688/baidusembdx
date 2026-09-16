"""Store shared rebate and recharge settings on account managers."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260914_0042"
down_revision = "20260913_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "account_managers",
        sa.Column("balance_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="search_marketing",
    )
    op.add_column(
        "account_managers",
        sa.Column("rebate_rate", sa.Numeric(7, 2), nullable=True),
        schema="search_marketing",
    )
    op.create_foreign_key(
        "fk_account_manager_balance_account",
        "account_managers",
        "accounts",
        ["balance_account_id"],
        ["id"],
        source_schema="search_marketing",
        referent_schema="search_marketing",
    )
    op.add_column(
        "account_managers",
        sa.Column("recharge_account", sa.String(200), nullable=True),
        schema="search_marketing",
    )
    # Existing installations keep their established value by promoting the
    # first bound account to the manager-level source of truth.
    op.execute(
        """
        UPDATE search_marketing.account_managers AS manager
        SET balance_account_id = (
            SELECT account.id
            FROM search_marketing.accounts AS account
            WHERE account.manager_id = manager.id
            ORDER BY account.baidu_account_id, account.id
            LIMIT 1
        ),
        rebate_rate = (
            SELECT account.rebate_rate
            FROM search_marketing.accounts AS account
            WHERE account.manager_id = manager.id
            ORDER BY account.baidu_account_id, account.id
            LIMIT 1
        ),
        recharge_account = (
            SELECT account.recharge_account
            FROM search_marketing.accounts AS account
            WHERE account.manager_id = manager.id
            ORDER BY account.baidu_account_id, account.id
            LIMIT 1
        )
        """
    )
    op.execute(
        """
        UPDATE search_marketing.accounts AS account
        SET rebate_rate = manager.rebate_rate,
            recharge_account = manager.recharge_account
        FROM search_marketing.account_managers AS manager
        WHERE account.manager_id = manager.id
          AND manager.login_name <> 'BDCC-发丹嘉w'
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_account_manager_balance_account",
        "account_managers",
        schema="search_marketing",
        type_="foreignkey",
    )
    op.drop_column("account_managers", "recharge_account", schema="search_marketing")
    op.drop_column("account_managers", "rebate_rate", schema="search_marketing")
    op.drop_column("account_managers", "balance_account_id", schema="search_marketing")
