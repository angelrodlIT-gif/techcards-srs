from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictBool, field_validator
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.db import get_db, lock_personal_write
from app.models import Card, Deck, ErrorLog, Review, Source
from app.pronunciation import recordings

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
        columns = [model.__table__.c[name] for name in ("identity " + fields).split()]
        rows = db.execute(select(*columns).order_by(model.id)).mappings()
        tables[model.__tablename__] = [
            {key: export_value(value) for key, value in row.items()} for row in rows
        ]
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = (
        'attachment; filename="techcards-personal-data-v1.json"'
    )
    return {"format_version": 1, "data": tables}


def delete_rows(db: Session, model, predicate) -> int:
    selected = select(model.id).where(predicate)
    card_filter = {
        Deck: Card.deck_id.in_(selected),
        Card: predicate,
        Source: Card.source_id.in_(selected),
        ErrorLog: Card.id.in_(select(ErrorLog.card_id).where(predicate)),
    }.get(model)
    recording_keys = (
        db.execute(select(Card.id, Card.identity).where(card_filter)).all()
        if card_filter is not None
        else []
    )
    if card_filter is not None and model is not Card:
        db.execute(delete(Card).where(card_filter))
    result = db.execute(delete(model).where(predicate).execution_options(synchronize_session=False))
    db.commit()
    for card_id, identity in recording_keys:
        recordings.delete_card(card_id, identity)
    return result.rowcount


@router.delete("/{collection}/{identifier}", status_code=204)
def erase_personal_row(
    collection: Collection,
    identifier: Annotated[int, Path(gt=0)],
    identity: Annotated[str, Query(pattern=r"^[0-9a-f]{32}$")],
    db: DB,
):
    lock_personal_write(db)
    model = MODELS[collection]
    predicate = (model.id == identifier) & (model.identity == identity)
    if db.scalar(select(model.id).where(predicate)) is None:
        raise HTTPException(404, "Personal data row not found")
    delete_rows(db, model, predicate)
    return Response(status_code=204)


@router.post("/retention", response_model=RetentionResult)
def retain(payload: RetentionInput, db: DB):
    model = MODELS[payload.collection]
    before = payload.before.astimezone(UTC)
    predicate = RETENTION_TIMESTAMPS[payload.collection] < before
    if payload.apply:
        lock_personal_write(db)
        matched = delete_rows(db, model, predicate)
    else:
        matched = db.scalar(select(func.count()).select_from(model).where(predicate))
    return RetentionResult(
        collection=payload.collection, before=before, applied=payload.apply, matched=matched
    )
