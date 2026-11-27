"""Identify the card revision associated with a local recording."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cards", sa.Column("pronunciation_revision", sa.String(32), nullable=True))


def downgrade():
    op.drop_column("cards", "pronunciation_revision")
