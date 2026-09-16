"""Add payment reconciliation and profit report persistence."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260916_0050"
down_revision = "20260916_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_payment_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manager_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fund_type", sa.Integer(), nullable=False),
        sa.Column("remote_record_id", sa.BigInteger(), nullable=False),
        sa.Column("pay_date", sa.Date(), nullable=False),
        sa.Column("pay_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("movement_type", sa.String(length=20), nullable=False),
        sa.Column("account_currency", sa.Numeric(16, 2), server_default="0", nullable=False),
        sa.Column("cash_amount", sa.Numeric(16, 2), server_default="0", nullable=False),
        sa.Column("bonus_amount", sa.Numeric(16, 2), server_default="0", nullable=False),
        sa.Column("pay_method_name", sa.String(length=200), nullable=True),
        sa.Column("product_name", sa.String(length=200), nullable=True),
        sa.Column("pending_type_name", sa.String(length=200), nullable=True),
        sa.Column("payment_status", sa.Integer(), nullable=True),
        sa.Column("payment_status_name", sa.String(length=100), nullable=True),
        sa.Column("order_row", sa.String(length=200), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("source_watermark", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["search_marketing.projects.id"]),
        sa.ForeignKeyConstraint(["manager_id"], ["search_marketing.account_managers.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["search_marketing.accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "manager_id", "fund_type", "remote_record_id"),
        schema="search_marketing",
    )
    op.create_index("ix_finance_payment_records_project_id", "finance_payment_records", ["project_id"], schema="search_marketing")
    op.create_index("ix_finance_payment_records_manager_id", "finance_payment_records", ["manager_id"], schema="search_marketing")
    op.create_index("ix_finance_payment_records_account_id", "finance_payment_records", ["account_id"], schema="search_marketing")
    op.create_index("ix_finance_payment_project_date", "finance_payment_records", ["project_id", "pay_date"], schema="search_marketing")
    op.create_index("ix_finance_payment_manager_date", "finance_payment_records", ["manager_id", "pay_date"], schema="search_marketing")

    op.create_table(
        "finance_profit_inputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("operator_scope", sa.String(length=500), server_default="__all__", nullable=False),
        sa.Column("reported_spend", sa.Numeric(16, 2), server_default="0", nullable=False),
        sa.Column("updated_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["search_marketing.projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "report_date", "operator_scope"),
        schema="search_marketing",
    )
    op.create_index("ix_finance_profit_inputs_project_id", "finance_profit_inputs", ["project_id"], schema="search_marketing")
    op.create_index("ix_finance_profit_project_date", "finance_profit_inputs", ["project_id", "report_date"], schema="search_marketing")

    op.execute("""
        UPDATE search_marketing.project_members
           SET permissions = jsonb_set(
               permissions,
               '{finance_reports}',
               to_jsonb(COALESCE(permissions->>'reports', 'hidden')),
               true
           )
    """)


def downgrade() -> None:
    op.execute("UPDATE search_marketing.project_members SET permissions = permissions - 'finance_reports'")
    op.drop_index("ix_finance_profit_project_date", table_name="finance_profit_inputs", schema="search_marketing")
    op.drop_index("ix_finance_profit_inputs_project_id", table_name="finance_profit_inputs", schema="search_marketing")
    op.drop_table("finance_profit_inputs", schema="search_marketing")
    op.drop_index("ix_finance_payment_manager_date", table_name="finance_payment_records", schema="search_marketing")
    op.drop_index("ix_finance_payment_project_date", table_name="finance_payment_records", schema="search_marketing")
    op.drop_index("ix_finance_payment_records_account_id", table_name="finance_payment_records", schema="search_marketing")
    op.drop_index("ix_finance_payment_records_manager_id", table_name="finance_payment_records", schema="search_marketing")
    op.drop_index("ix_finance_payment_records_project_id", table_name="finance_payment_records", schema="search_marketing")
    op.drop_table("finance_payment_records", schema="search_marketing")
