"""Create interview_sessions and interview_turns tables for mock interviews."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "interview_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('cloud_support', 'junior_aws', 'python_backend')"),
        sa.CheckConstraint("status IN ('active', 'completed')"),
    )
    op.create_table(
        "interview_turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("turn_type", sa.String(20), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("english_clarity", sa.Text(), nullable=True),
        sa.Column("technical_accuracy", sa.Text(), nullable=True),
        sa.Column("star_structure", sa.Text(), nullable=True),
        sa.Column("corrected_phrasing", sa.Text(), nullable=True),
        sa.Column("uncertainty_note", sa.Text(), nullable=True),
        sa.Column("human_review_status", sa.String(20), nullable=False),
        sa.Column("human_notes", sa.Text(), nullable=True),
        sa.CheckConstraint("turn_index >= 1"),
        sa.CheckConstraint("turn_type IN ('technical', 'follow_up', 'behavioral')"),
        sa.CheckConstraint("human_review_status IN ('pending', 'accepted', 'edited', 'dismissed')"),
    )
    op.create_index("ix_interview_turns_session_id", "interview_turns", ["session_id"])
    op.create_index(
        "uq_interview_turns_session_turn",
        "interview_turns",
        ["session_id", "turn_index"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_interview_turns_session_turn", table_name="interview_turns")
    op.drop_index("ix_interview_turns_session_id", table_name="interview_turns")
    op.drop_table("interview_turns")
    op.drop_table("interview_sessions")
