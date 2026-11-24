"""Create error_logs table for manual error-to-card curation."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "error_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attempted", sa.Text(), nullable=False),
        sa.Column("corrected", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "card_id", sa.Integer(), sa.ForeignKey("cards.id", ondelete="SET NULL"), nullable=True
        ),
        sa.CheckConstraint("status IN ('draft', 'approved', 'discarded')"),
    )
    op.create_index(
        "uq_error_logs_card_id",
        "error_logs",
        ["card_id"],
        unique=True,
        postgresql_where=sa.text("card_id IS NOT NULL"),
        sqlite_where=sa.text("card_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_error_logs_card_id", table_name="error_logs")
    op.drop_table("error_logs")
