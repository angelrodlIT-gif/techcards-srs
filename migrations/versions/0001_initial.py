"""Create decks, cards and review events."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "decks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
    )
    op.create_table(
        "cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "deck_id", sa.Integer(), sa.ForeignKey("decks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("ease_factor", sa.Double(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.CheckConstraint("repetitions >= 0 AND interval_days >= 0 AND ease_factor >= 1.3"),
    )
    op.create_index("ix_cards_deck_due", "cards", ["deck_id", "due_date"])
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "card_id", sa.Integer(), sa.ForeignKey("cards.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("quality", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("ease_factor", sa.Double(), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.CheckConstraint("quality >= 0 AND quality <= 5"),
    )
    op.create_index("ix_reviews_card_id", "reviews", ["card_id"])


def downgrade():
    op.drop_table("reviews")
    op.drop_table("cards")
    op.drop_table("decks")
