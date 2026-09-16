"""Persist canonical UTF-8 URL encoding for every material keyword."""

from urllib.parse import quote

import sqlalchemy as sa
from alembic import op


revision = "20260714_0019"
down_revision = "20260714_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "material_keywords",
        sa.Column("keyword_utf8_encoded", sa.Text(), nullable=True),
        schema="search_marketing",
    )
    op.add_column(
        "material_keywords",
        sa.Column(
            "keyword_encoding_version",
            sa.String(length=32),
            nullable=False,
            server_default="utf8-rfc3986-v1",
        ),
        schema="search_marketing",
    )

    connection = op.get_bind()
    rows = connection.execute(sa.text("""
        SELECT id, keyword_text
          FROM search_marketing.material_keywords
         WHERE keyword_utf8_encoded IS NULL
         ORDER BY id
    """)).mappings().all()
    update_statement = sa.text("""
        UPDATE search_marketing.material_keywords
           SET keyword_utf8_encoded = :encoded
         WHERE id = :id
    """)
    batch_size = 2000
    for offset in range(0, len(rows), batch_size):
        values = [
            {
                "id": row["id"],
                "encoded": quote(
                    str(row["keyword_text"]).strip(),
                    safe="",
                    encoding="utf-8",
                    errors="strict",
                ),
            }
            for row in rows[offset:offset + batch_size]
        ]
        connection.execute(update_statement, values)

    op.alter_column(
        "material_keywords",
        "keyword_utf8_encoded",
        existing_type=sa.Text(),
        nullable=False,
        schema="search_marketing",
    )


def downgrade() -> None:
    op.drop_column("material_keywords", "keyword_encoding_version", schema="search_marketing")
    op.drop_column("material_keywords", "keyword_utf8_encoded", schema="search_marketing")
