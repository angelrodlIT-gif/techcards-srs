"""Give existing and new decks a stable identity across integer ID reuse."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("decks", sa.Column("incarnation", sa.String(32), nullable=True))
    random_hex = (
        "lower(hex(randomblob(16)))"
        if op.get_context().dialect.name == "sqlite"
        else "replace(gen_random_uuid()::text, '-', '')"
    )
    op.execute(sa.text(f"UPDATE decks SET incarnation = {random_hex}"))
    with op.batch_alter_table("decks") as batch:
        batch.alter_column(
            "incarnation",
            existing_type=sa.String(32),
            nullable=False,
            server_default=sa.text(f"({random_hex})"),
        )


def downgrade():
    with op.batch_alter_table("decks") as batch:
        batch.drop_column("incarnation")
