"""Create sources table for manual source-to-card curation."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("normalized_url", sa.String(2048), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'approved', 'discarded')"),
    )
    op.create_index(
        "uq_sources_normalized_url",
        "sources",
        ["normalized_url"],
        unique=True,
        postgresql_where=sa.text("normalized_url IS NOT NULL"),
        sqlite_where=sa.text("normalized_url IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_sources_normalized_url", table_name="sources")
    op.drop_table("sources")
