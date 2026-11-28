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


def recover_sqlite_cards():
    # Legacy databases cannot prove either side of a numeric foreign key survived.
    # Reserve a fresh deck and keep orphan reviews visible on placeholder cards.
    connection = op.get_bind()
    recovery_id = connection.execute(
        sa.text("""
        INSERT INTO decks (name, description)
        SELECT 'Recovered SQLite cards', 'Review legacy cards and move them to the intended decks.'
        WHERE EXISTS (SELECT 1 FROM cards) OR EXISTS (SELECT 1 FROM reviews)
        RETURNING id
        """)
    ).scalar_one_or_none()
    if recovery_id is None:
        return
    op.execute(sa.text("UPDATE cards SET deck_id = :id").bindparams(id=recovery_id))
    op.execute(
        sa.text("""
        INSERT INTO cards (id, deck_id, front, back, kind, repetitions,
                           interval_days, ease_factor, due_date)
        SELECT DISTINCT reviews.card_id, :id,
               'Missing legacy card', 'Review history preserved for manual inspection.',
               'vocabulary', 0, 0, 2.5, '9999-12-31'
        FROM reviews
        WHERE NOT EXISTS (SELECT 1 FROM cards WHERE cards.id = reviews.card_id)
        """).bindparams(id=recovery_id)
    )


def upgrade():
    sqlite = op.get_context().dialect.name == "sqlite"
    if sqlite:
        # Legacy SQLite did not enforce foreign keys. A matching ID alone cannot
        # distinguish an approved card from a replacement created before upgrade.
        op.execute("UPDATE error_logs SET card_id = NULL WHERE card_id IS NOT NULL")
        recover_sqlite_cards()
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
