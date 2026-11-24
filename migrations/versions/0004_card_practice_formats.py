"""Add nullable accepted_answers and explanation columns to cards."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cards", sa.Column("accepted_answers", sa.JSON(), nullable=True))
    op.add_column("cards", sa.Column("explanation", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("cards", "explanation")
    op.drop_column("cards", "accepted_answers")
