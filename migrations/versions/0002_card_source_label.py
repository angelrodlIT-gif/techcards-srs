"""Add nullable source_label column to cards."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cards", sa.Column("source_label", sa.String(255), nullable=True))


def downgrade():
    op.drop_column("cards", "source_label")
