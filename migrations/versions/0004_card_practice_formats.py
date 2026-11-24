"""Add nullable accepted_answers and explanation columns to cards.

Downgrade performs a lossy remap of sentence/cloze/es_en cards to vocabulary
before dropping the new columns so rolled-back rows remain readable on the
pre-0004 API (original kinds are not recovered on a later upgrade).
"""

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
    op.execute(
        sa.text("UPDATE cards SET kind = 'vocabulary' WHERE kind IN ('sentence', 'cloze', 'es_en')")
    )
    op.drop_column("cards", "explanation")
    op.drop_column("cards", "accepted_answers")
