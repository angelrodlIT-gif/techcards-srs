from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictBool, field_validator
from sqlalchemy import delete, func, select, text
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


def delete_errors(db: Session, condition, *, delete_cards: bool = True) -> int:
    # Approvals lock the error row and create a fresh card in one transaction.
    # RETURNING sees the final link if a concurrent approval committed first.
    card_ids = (
        db.execute(delete(ErrorLog).where(condition).returning(ErrorLog.card_id)).scalars().all()
    )
    if not delete_cards:
        return len(card_ids)
    linked_ids = [card_id for card_id in card_ids if card_id is not None]
    for offset in range(0, len(linked_ids), 500):
        db.execute(delete(Card).where(Card.id.in_(linked_ids[offset : offset + 500])))
    return len(card_ids)


def delete_source(db: Session, source_id: int) -> int:
    # Source approval holds the same lock while creating its linked card.
    if db.scalar(select(Source.id).where(Source.id == source_id).with_for_update()) is None:
        return 0
    db.execute(delete(Card).where(Card.source_id == source_id))
    db.execute(delete(Source).where(Source.id == source_id))
    return 1


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
        else:
            matched = db.execute(delete(model).where(model.id == row_id)).rowcount
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
            matched = db.execute(delete(model).where(condition)).rowcount
    return RetentionResult(
        collection=payload.collection, before=before, applied=payload.apply, matched=matched
    )
