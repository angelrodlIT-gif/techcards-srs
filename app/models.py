from datetime import UTC, date, datetime

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Deck(Base):
    __tablename__ = "decks"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint("repetitions >= 0 AND interval_days >= 0 AND ease_factor >= 1.3"),
        Index("ix_cards_deck_due", "deck_id", "due_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"))
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="vocabulary")
    source_label: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    accepted_answers: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    repetitions: Mapped[int] = mapped_column(default=0)
    interval_days: Mapped[int] = mapped_column(default=0)
    ease_factor: Mapped[float] = mapped_column(default=2.5)
    due_date: Mapped[date] = mapped_column(Date, default=lambda: datetime.now(UTC).date())
    error_log: Mapped["ErrorLog | None"] = relationship(
        "ErrorLog", back_populates="card", uselist=False
    )

    @property
    def error_id(self) -> int | None:
        return self.error_log.id if self.error_log is not None else None


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (CheckConstraint("quality >= 0 AND quality <= 5"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    quality: Mapped[int]
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    interval_days: Mapped[int]
    ease_factor: Mapped[float]
    repetitions: Mapped[int]
    due_date: Mapped[date]


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'approved', 'discarded')"),
        Index(
            "uq_sources_normalized_url",
            "normalized_url",
            unique=True,
            postgresql_where=text("normalized_url IS NOT NULL"),
            sqlite_where=text("normalized_url IS NOT NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True, default=None)
    normalized_url: Mapped[str | None] = mapped_column(String(2048), nullable=True, default=None)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(20), default="draft")


class ErrorLog(Base):
    __tablename__ = "error_logs"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'approved', 'discarded')"),
        Index(
            "uq_error_logs_card_id",
            "card_id",
            unique=True,
            postgresql_where=text("card_id IS NOT NULL"),
            sqlite_where=text("card_id IS NOT NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    attempted: Mapped[str] = mapped_column(Text)
    corrected: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), nullable=True, default=None
    )
    card: Mapped[Card | None] = relationship("Card", back_populates="error_log")


class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        CheckConstraint("role IN ('cloud_support', 'junior_aws', 'python_backend')"),
        CheckConstraint("status IN ('active', 'completed')"),
        {"sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    turns: Mapped[list["InterviewTurn"]] = relationship(
        "InterviewTurn",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="InterviewTurn.turn_index",
    )


class InterviewTurn(Base):
    __tablename__ = "interview_turns"
    __table_args__ = (
        CheckConstraint("turn_index >= 1"),
        CheckConstraint("turn_type IN ('technical', 'follow_up', 'behavioral')"),
        CheckConstraint("human_review_status IN ('pending', 'accepted', 'edited', 'dismissed')"),
        Index("uq_interview_turns_session_turn", "session_id", "turn_index", unique=True),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True
    )
    turn_index: Mapped[int]
    turn_type: Mapped[str] = mapped_column(String(20))
    prompt: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    english_clarity: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    technical_accuracy: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    star_structure: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    corrected_phrasing: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    uncertainty_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    human_review_status: Mapped[str] = mapped_column(String(20), default="pending")
    human_notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    session: Mapped[InterviewSession] = relationship("InterviewSession", back_populates="turns")
