"""Initial platform and search schemas."""
from alembic import op
from search_console.db import Base
from search_console import models  # noqa: F401
from baidu_platform_core.schema import ensure_platform_schema

revision = "20260713_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE SCHEMA IF NOT EXISTS search_marketing")
    ensure_platform_schema(bind.engine)
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

