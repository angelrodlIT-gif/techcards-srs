from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictBool, field_validator
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Card, Deck, ErrorLog, Review, Source

router = APIRouter(prefix="/personal-data", tags=["personal data"])
DB = Annotated[Session, Depends(get_db)]
Collection = Literal["decks", "cards", "reviews", "error_logs", "sources"]
TimedCollection = Literal["reviews", "error_logs"]

# The export format names its fields explicitly so new storage stays private until reviewed.
EXPORT_FIELDS = {
    Deck: "id name description",
    Card: (
        "id deck_id front back kind source_label source_id accepted_answers explanation "
        "repetitions interval_days ease_factor due_date"
    ),
    Review: "id card_id quality reviewed_at interval_days ease_factor repetitions due_date",
    ErrorLog: "id attempted corrected rationale status card_id created_at",
    Source: "id label url normalized_url excerpt status",
}
MODELS = {model.__tablename__: model for model in EXPORT_FIELDS}
RETENTION_TIMESTAMPS = {"reviews": Review.reviewed_at, "error_logs": ErrorLog.created_at}


class RetentionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection: TimedCollection
    before: AwareDatetime
    apply: StrictBool = False

    @field_validator("before", mode="before")
    @classmethod
    def require_date_time(cls, value):
        if not isinstance(value, str) or "T" not in value:
            raise ValueError("Use an ISO 8601 date and time with a timezone offset")
        return value


class RetentionResult(BaseModel):
    collection: TimedCollection
    before: AwareDatetime
    applied: bool
    matched: int


def export_value(value):
    if isinstance(value, datetime):
        # SQLite returns naive datetimes for timestamps written in UTC.
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
    return value


@router.get("/export")
def export_personal_data(db: DB, response: Response):
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    elif db.get_bind().dialect.name == "sqlite":
        # The sqlite3 legacy transaction mode does not begin a transaction on SELECT.
        db.execute(text("BEGIN"))

    tables = {}
    for model, fields in EXPORT_FIELDS.items():
        columns = [model.__table__.c[name] for name in fields.split()]
        rows = db.execute(select(*columns).order_by(model.id)).mappings()
        tables[model.__tablename__] = [
            {key: export_value(value) for key, value in row.items()} for row in rows
        ]
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = (
        'attachment; filename="techcards-personal-data-v1.json"'
    )
    return {"format_version": 1, "data": tables}


BATCH_SIZE = 500


def _chunks(values: list[int]):
    for offset in range(0, len(values), BATCH_SIZE):
        yield values[offset : offset + BATCH_SIZE]


def _lock_error_logs_for_cards(db: Session, card_ids_subquery) -> None:
    db.execute(
        select(ErrorLog.id)
        .where(ErrorLog.card_id.in_(card_ids_subquery))
        .order_by(ErrorLog.id)
        .with_for_update(of=ErrorLog)
    ).all()


def _delete_locked_cards(db: Session, card_ids: list[int]) -> None:
    # Cards are already locked FOR UPDATE in PK order, so no new reviews can be
    # added while we lock and delete existing reviews in PK order.
    review_ids: list[int] = []
    for batch in _chunks(card_ids):
        review_ids.extend(db.scalars(select(Review.id).where(Review.card_id.in_(batch))).all())
    if review_ids:
        review_ids.sort()
        for batch in _chunks(review_ids):
            db.execute(
                select(Review.id).where(Review.id.in_(batch)).order_by(Review.id).with_for_update()
            ).all()
        for batch in _chunks(review_ids):
            db.execute(delete(Review).where(Review.id.in_(batch)))
    for batch in _chunks(card_ids):
        db.execute(delete(Card).where(Card.id.in_(batch)))


def _unlink_and_delete_locked_cards(db: Session, card_ids: list[int]) -> None:
    for batch in _chunks(card_ids):
        db.execute(update(ErrorLog).where(ErrorLog.card_id.in_(batch)).values(card_id=None))
    _delete_locked_cards(db, card_ids)


def _acquire_sqlite_write_lock(db: Session) -> None:
    if db.get_bind().dialect.name != "sqlite":
        return
    conn = db.connection()
    raw = conn.connection.dbapi_connection
    if not getattr(raw, "in_transaction", False):
        # In sqlite3's legacy transaction mode, SELECT neither begins a transaction
        # nor acquires a write lock; BEGIN IMMEDIATE keeps selection and deletion atomic.
        conn.exec_driver_sql("BEGIN IMMEDIATE")


# Canonical lock order across all deletion and retention paths:
# decks / sources -> error_logs (id) -> cards (id) -> reviews (id).
def delete_errors(db: Session, condition, *, delete_cards: bool = True) -> int:
    _acquire_sqlite_write_lock(db)
    # Approvals also lock the error row first, so FOR UPDATE sees any card_id
    # committed by a concurrent approval.
    rows = db.execute(
        select(ErrorLog.id, ErrorLog.card_id)
        .where(condition)
        .order_by(ErrorLog.id)
        .with_for_update()
    ).all()
    if not rows:
        return 0
    error_ids = [row.id for row in rows]
    card_ids = sorted({row.card_id for row in rows if row.card_id is not None})
    if delete_cards and card_ids:
        for batch in _chunks(card_ids):
            db.execute(
                select(Card.id).where(Card.id.in_(batch)).order_by(Card.id).with_for_update()
            ).all()
    for batch in _chunks(error_ids):
        db.execute(delete(ErrorLog).where(ErrorLog.id.in_(batch), condition))
    if delete_cards and card_ids:
        _delete_locked_cards(db, card_ids)
    return len(error_ids)


def delete_card(db: Session, card_id: int) -> int:
    _acquire_sqlite_write_lock(db)
    db.execute(
        select(ErrorLog.id)
        .where(ErrorLog.card_id == card_id)
        .order_by(ErrorLog.id)
        .with_for_update(of=ErrorLog)
    ).all()
    if db.scalar(select(Card.id).where(Card.id == card_id).with_for_update()) is None:
        return 0
    _unlink_and_delete_locked_cards(db, [card_id])
    return 1


def delete_deck(db: Session, deck_id: int) -> int:
    _acquire_sqlite_write_lock(db)
    if db.scalar(select(Deck.id).where(Deck.id == deck_id).with_for_update()) is None:
        return 0
    _lock_error_logs_for_cards(db, select(Card.id).where(Card.deck_id == deck_id))
    card_ids = list(
        db.scalars(
            select(Card.id).where(Card.deck_id == deck_id).order_by(Card.id).with_for_update()
        )
    )
    if card_ids:
        _unlink_and_delete_locked_cards(db, card_ids)
    db.execute(delete(Deck).where(Deck.id == deck_id))
    return 1


def delete_source(db: Session, source_id: int, *, delete_cards: bool = True) -> int:
    _acquire_sqlite_write_lock(db)
    # Source approval holds the same lock while creating its linked card.
    if db.scalar(select(Source.id).where(Source.id == source_id).with_for_update()) is None:
        return 0
    if delete_cards:
        _lock_error_logs_for_cards(db, select(Card.id).where(Card.source_id == source_id))
    card_ids = list(
        db.scalars(
            select(Card.id).where(Card.source_id == source_id).order_by(Card.id).with_for_update()
        )
    )
    if card_ids:
        if delete_cards:
            _unlink_and_delete_locked_cards(db, card_ids)
        else:
            for batch in _chunks(card_ids):
                db.execute(update(Card).where(Card.id.in_(batch)).values(source_id=None))
    db.execute(delete(Source).where(Source.id == source_id))
    return 1


def delete_reviews(db: Session, condition) -> int:
    _acquire_sqlite_write_lock(db)
    review_ids = list(
        db.scalars(select(Review.id).where(condition).order_by(Review.id).with_for_update())
    )
    for batch in _chunks(review_ids):
        db.execute(delete(Review).where(Review.id.in_(batch), condition))
    return len(review_ids)


@router.delete("/{collection}/{row_id}", status_code=204)
def delete_personal_row(
    collection: Collection, row_id: Annotated[int, Path(gt=0, le=2**31 - 1)], db: DB
):
    model = MODELS[collection]
    with db.begin():
        if model is ErrorLog:
            matched = delete_errors(db, ErrorLog.id == row_id)
        elif model is Source:
            matched = delete_source(db, row_id)
        elif model is Deck:
            matched = delete_deck(db, row_id)
        elif model is Card:
            matched = delete_card(db, row_id)
        else:
            matched = delete_reviews(db, Review.id == row_id)
        if not matched:
            raise HTTPException(404, "Personal data row not found")


@router.post("/retention")
def retain_personal_data(payload: RetentionInput, db: DB) -> RetentionResult:
    model = MODELS[payload.collection]
    before = payload.before.astimezone(UTC)
    condition = RETENTION_TIMESTAMPS[payload.collection] < before
    with db.begin():
        if not payload.apply:
            matched = db.scalar(select(func.count()).select_from(model).where(condition))
        elif model is ErrorLog:
            matched = delete_errors(db, condition)
        else:
            matched = delete_reviews(db, condition)
    return RetentionResult(
        collection=payload.collection, before=before, applied=payload.apply, matched=matched
    )
