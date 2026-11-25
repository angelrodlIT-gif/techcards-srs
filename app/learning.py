from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import null, select
from sqlalchemy.orm import Session

from app.models import ErrorLog, Review

CANCUN = ZoneInfo("America/Cancun")
SESSION_GAP = timedelta(minutes=30)


class OutcomeCount(BaseModel):
    numerator: int = 0
    denominator: int = 0


class ReviewMetrics(BaseModel):
    recall: OutcomeCount = Field(default_factory=OutcomeCount)
    lapse: OutcomeCount = Field(default_factory=OutcomeCount)


class PracticeMetrics(BaseModel):
    sessions: int = 0
    first_review_at: datetime | None = None
    last_review_at: datetime | None = None
    first_review_cancun_date: date | None = None
    last_review_cancun_date: date | None = None
    observed_span_seconds: float | None = None
    active_study_seconds: None = None
    response_seconds: None = None


class ErrorCorrectionMetrics(BaseModel):
    current_drafts: int
    current_discarded: int
    current_approved: int
    current_approved_without_card: int
    first_review_recall: OutcomeCount


class DataQuality(BaseModel):
    reviews_without_timestamp: int = 0
    reviews_with_invalid_grade: int = 0
    possible_duplicate_reviews: int = 0


class LearningSummary(BaseModel):
    semantics_version: Literal[1] = 1
    date_timezone: Literal["America/Cancun"] = "America/Cancun"
    start: date | None
    end: date | None
    reviews: ReviewMetrics
    practice: PracticeMetrics
    error_correction: ErrorCorrectionMetrics
    data_quality: DataQuality


def summarize_learning(db: Session, start: date | None, end: date | None) -> LearningSummary:
    # Read both sources in one statement so they describe the same database snapshot.
    rows = db.execute(
        select(Review.id, Review.card_id, Review.quality, Review.reviewed_at, null()).union_all(
            select(null(), ErrorLog.card_id, null(), null(), ErrorLog.status)
        )
    )
    statuses: Counter[str] = Counter()
    approved_cards: set[int] = set()
    undated_cards: set[int] = set()
    dated_reviews: list[tuple[datetime, int, int, int]] = []
    data_quality = DataQuality()
    for review_id, card_id, quality, reviewed_at, error_status in rows:
        if review_id is None:
            statuses[error_status] += 1
            if error_status == "approved" and card_id is not None:
                approved_cards.add(card_id)
        elif reviewed_at is None:
            undated_cards.add(card_id)
            data_quality.reviews_without_timestamp += 1
        else:
            # SQLite drops the offset when storing the app's UTC timestamps.
            if reviewed_at.utcoffset() is None:
                reviewed_at = reviewed_at.replace(tzinfo=UTC)
            dated_reviews.append((reviewed_at.astimezone(UTC), review_id, card_id, quality))

    reviews = ReviewMetrics()
    practice = PracticeMetrics()
    first_review_recall = OutcomeCount()
    previous_grade: dict[int, bool | None] = {}
    seen_attempts: set[tuple[int, datetime, int]] = set()
    span = timedelta()
    for reviewed_at, _, card_id, quality in sorted(dated_reviews):
        cancun_date = reviewed_at.astimezone(CANCUN).date()
        if end is not None and cancun_date > end:
            continue
        in_range = start is None or cancun_date >= start
        first_review = card_id not in previous_grade
        was_passing = previous_grade.get(card_id)
        if type(quality) is not int or not 0 <= quality <= 5:
            previous_grade[card_id] = None
            data_quality.reviews_with_invalid_grade += in_range
            continue
        passing = quality >= 3
        previous_grade[card_id] = passing
        if not in_range:
            continue

        reviews.recall.denominator += 1
        reviews.recall.numerator += passing
        if was_passing and card_id not in undated_cards:
            reviews.lapse.denominator += 1
            reviews.lapse.numerator += not passing
        if first_review and card_id in approved_cards and card_id not in undated_cards:
            first_review_recall.denominator += 1
            first_review_recall.numerator += passing

        attempt = (card_id, reviewed_at, quality)
        data_quality.possible_duplicate_reviews += attempt in seen_attempts
        seen_attempts.add(attempt)
        if practice.last_review_at is None:
            practice.first_review_at = reviewed_at
            practice.first_review_cancun_date = cancun_date
            practice.sessions = 1
        else:
            gap = reviewed_at - practice.last_review_at
            if gap > SESSION_GAP:
                practice.sessions += 1
            else:
                span += gap
        practice.last_review_at = reviewed_at
        practice.last_review_cancun_date = cancun_date
    if practice.sessions:
        practice.observed_span_seconds = span.total_seconds()

    return LearningSummary(
        start=start,
        end=end,
        reviews=reviews,
        practice=practice,
        error_correction=ErrorCorrectionMetrics(
            current_drafts=statuses["draft"],
            current_discarded=statuses["discarded"],
            current_approved=statuses["approved"],
            current_approved_without_card=statuses["approved"] - len(approved_cards),
            first_review_recall=first_review_recall,
        ),
        data_quality=data_quality,
    )
