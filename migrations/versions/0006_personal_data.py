"""Track source derivatives and the age of new error logs."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def card_checks():
    # SQLite batch operations omit unnamed checks when they recreate the table.
    return (sa.CheckConstraint("repetitions >= 0 AND interval_days >= 0 AND ease_factor >= 1.3"),)


def upgrade():
    # Pre-0006 SQLite connections ran without PRAGMA foreign_keys=ON, so deleted
    # decks or cards could leave orphaned children or dangling error-log links.
    # Clean them up before FK enforcement is enabled so reused SQLite IDs cannot
    # reattach old rows to unrelated parents.
    op.execute(
        sa.text(
            "DELETE FROM cards "
            "WHERE NOT EXISTS (SELECT 1 FROM decks WHERE decks.id = cards.deck_id)"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM reviews "
            "WHERE NOT EXISTS (SELECT 1 FROM cards WHERE cards.id = reviews.card_id)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE error_logs SET card_id = NULL "
            "WHERE card_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM cards WHERE cards.id = error_logs.card_id)"
        )
    )
    with op.batch_alter_table("cards", table_args=card_checks()) as batch:
        batch.add_column(sa.Column("source_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_cards_source_id", "sources", ["source_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_cards_source_id", ["source_id"])
    op.add_column("error_logs", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("error_logs", "created_at")
    with op.batch_alter_table("cards", table_args=card_checks()) as batch:
        batch.drop_index("ix_cards_source_id")
        batch.drop_constraint("fk_cards_source_id", type_="foreignkey")
        batch.drop_column("source_id")
