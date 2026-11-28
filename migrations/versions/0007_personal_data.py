"""Give personal rows stable identities and track derivative provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TABLES = ("decks", "cards", "reviews", "sources", "error_logs")


def card_checks():
    # Alembic batch mode does not copy unnamed SQLite CHECK constraints.
    return (sa.CheckConstraint("repetitions >= 0 AND interval_days >= 0 AND ease_factor >= 1.3"),)


def upgrade():
    sqlite = op.get_context().dialect.name == "sqlite"
    if sqlite:
        # Legacy SQLite did not enforce foreign keys. A matching ID alone cannot
        # distinguish an approved card from a replacement created before upgrade.
        op.execute("UPDATE error_logs SET card_id = NULL WHERE card_id IS NOT NULL")
        op.execute("DELETE FROM cards WHERE deck_id NOT IN (SELECT id FROM decks)")
        op.execute("DELETE FROM reviews WHERE card_id NOT IN (SELECT id FROM cards)")
    with op.batch_alter_table("cards", table_args=card_checks() if sqlite else ()) as batch:
        batch.add_column(sa.Column("source_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_cards_source_id", "sources", ["source_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_cards_source_id", ["source_id"])
    op.add_column("error_logs", sa.Column("created_at", sa.DateTime(timezone=True)))
    identity = (
        "lower(hex(randomblob(16)))" if sqlite else "replace(gen_random_uuid()::text, '-', '')"
    )
    for table in TABLES:
        op.add_column(table, sa.Column("identity", sa.String(32)))
        op.execute(f"UPDATE {table} SET identity = {identity}")


def downgrade():
    for table in TABLES:
        op.drop_column(table, "identity")
    op.drop_column("error_logs", "created_at")
    sqlite = op.get_context().dialect.name == "sqlite"
    with op.batch_alter_table("cards", table_args=card_checks() if sqlite else ()) as batch:
        batch.drop_index("ix_cards_source_id")
        batch.drop_constraint("fk_cards_source_id", type_="foreignkey")
        batch.drop_column("source_id")
