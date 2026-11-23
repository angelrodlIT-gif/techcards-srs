from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.generator import CardGenerator, get_generator
from app.models import Card, Deck, Review, Source
from app.schemas import (
    CardInput,
    CardOut,
    DeckInput,
    DeckOut,
    GenerateInput,
    ReviewInput,
    ReviewOut,
    SourceApproveInput,
    SourceApproveOut,
    SourceInput,
    SourceOut,
    SourceStatus,
)
from app.sm2 import Schedule, schedule_review


def utc_now() -> datetime:
    return datetime.now(UTC)


def get_clock() -> Callable[[], datetime]:
    return utc_now


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


app = FastAPI(title="TechCards SRS", version="0.1.0")
DB = Annotated[Session, Depends(get_db)]
Generator = Annotated[CardGenerator, Depends(get_generator)]
Clock = Annotated[Callable[[], datetime], Depends(get_clock)]


def require(db: Session, model, identifier: int):
    obj = db.get(model, identifier)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return obj


def save(db: Session, obj):
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/decks", response_model=DeckOut, status_code=201)
def create_deck(payload: DeckInput, db: DB):
    return save(db, Deck(**payload.model_dump()))


@app.get("/decks", response_model=list[DeckOut])
def list_decks(db: DB, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)):
    return db.scalars(select(Deck).order_by(Deck.id).offset(offset).limit(limit)).all()


@app.get("/decks/{deck_id}", response_model=DeckOut)
def get_deck(deck_id: int, db: DB):
    return require(db, Deck, deck_id)


@app.put("/decks/{deck_id}", response_model=DeckOut)
def update_deck(deck_id: int, payload: DeckInput, db: DB):
    deck = require(db, Deck, deck_id)
    deck.name, deck.description = payload.name, payload.description
    return save(db, deck)


@app.delete("/decks/{deck_id}", status_code=204)
def delete_deck(deck_id: int, db: DB):
    db.delete(require(db, Deck, deck_id))
    db.commit()
    return Response(status_code=204)


@app.get("/decks/{deck_id}/due", response_model=list[CardOut])
def due_cards(
    deck_id: int,
    db: DB,
    clock: Clock,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
):
    require(db, Deck, deck_id)
    today = normalize_utc(clock()).date()
    return db.scalars(
        select(Card)
        .where(Card.deck_id == deck_id, Card.due_date <= today)
        .order_by(Card.due_date, Card.id)
        .offset(offset)
        .limit(limit)
    ).all()


# Register this static path before /cards/{card_id}.
@app.post("/cards/generate", response_model=list[CardOut], status_code=201)
def generate_cards(payload: GenerateInput, db: DB, generator: Generator, clock: Clock):
    require(db, Deck, payload.deck_id)
    generated = generator.generate(payload.text, payload.max_cards)
    today = normalize_utc(clock()).date()
    # Validate provider output before any rows are persisted.
    cards = [
        Card(
            **CardInput(
                deck_id=payload.deck_id, front=c.front, back=c.back, kind=c.kind
            ).model_dump(),
            due_date=today,
        )
        for c in generated[: payload.max_cards]
    ]
    db.add_all(cards)
    db.commit()
    for card in cards:
        db.refresh(card)
    return cards


@app.post("/cards", response_model=CardOut, status_code=201)
def create_card(payload: CardInput, db: DB, clock: Clock):
    require(db, Deck, payload.deck_id)
    today = normalize_utc(clock()).date()
    return save(db, Card(**payload.model_dump(), due_date=today))


@app.get("/cards", response_model=list[CardOut])
def list_cards(
    db: DB,
    deck_id: int | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
):
    query = select(Card).order_by(Card.id)
    if deck_id is not None:
        require(db, Deck, deck_id)
        query = query.where(Card.deck_id == deck_id)
    return db.scalars(query.offset(offset).limit(limit)).all()


@app.get("/cards/{card_id}", response_model=CardOut)
def get_card(card_id: int, db: DB):
    return require(db, Card, card_id)


@app.put("/cards/{card_id}", response_model=CardOut)
def update_card(card_id: int, payload: CardInput, db: DB):
    card = require(db, Card, card_id)
    require(db, Deck, payload.deck_id)
    for key, value in payload.model_dump().items():
        setattr(card, key, value)
    return save(db, card)


@app.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: int, db: DB):
    db.delete(require(db, Card, card_id))
    db.commit()
    return Response(status_code=204)


@app.post("/reviews", response_model=ReviewOut, status_code=201)
def create_review(payload: ReviewInput, db: DB, clock: Clock):
    # PostgreSQL serializes reviews for the same card; SQLite is for sequential unit tests.
    try:
        card = db.scalar(select(Card).where(Card.id == payload.card_id).with_for_update())
        if card is None:
            raise HTTPException(404, "Card not found")
        now = normalize_utc(clock())
        result = schedule_review(
            Schedule(card.repetitions, card.interval_days, card.ease_factor),
            payload.quality,
            now.date(),
        )
        card.repetitions = result.schedule.repetitions
        card.interval_days = result.schedule.interval_days
        card.ease_factor = result.schedule.ease_factor
        card.due_date = result.due_date
        review = Review(
            card_id=card.id,
            quality=payload.quality,
            reviewed_at=now,
            interval_days=card.interval_days,
            ease_factor=card.ease_factor,
            repetitions=card.repetitions,
            due_date=card.due_date,
        )
        db.add(review)
        db.flush()
        review_out = ReviewOut.model_validate(review)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return review_out


def ensure_unique_source_url(
    db: Session, normalized_url: str | None, exclude_id: int | None = None
) -> None:
    if normalized_url is None:
        return
    query = select(Source.id).where(Source.normalized_url == normalized_url)
    if exclude_id is not None:
        query = query.where(Source.id != exclude_id)
    if db.scalar(query) is not None:
        raise HTTPException(409, "A source with this URL already exists")


def save_source(db: Session, source: Source) -> Source:
    try:
        return save(db, source)
    except IntegrityError as exc:
        db.rollback()
        if source.normalized_url is not None:
            raise HTTPException(409, "A source with this URL already exists") from exc
        raise


def lock_draft_source(db: Session, source_id: int, action: str) -> Source:
    source = db.scalar(select(Source).where(Source.id == source_id).with_for_update())
    if source is None:
        raise HTTPException(404, "Source not found")
    if source.status != "draft":
        raise HTTPException(409, f"Cannot {action} source in '{source.status}' status")
    return source


@app.post("/sources", response_model=SourceOut, status_code=201)
def create_source(payload: SourceInput, db: DB):
    normalized_url = payload.normalized_url
    ensure_unique_source_url(db, normalized_url)
    source = Source(
        label=payload.label,
        url=payload.url,
        normalized_url=normalized_url,
        excerpt=payload.excerpt,
        status="draft",
    )
    return save_source(db, source)


@app.get("/sources", response_model=list[SourceOut])
def list_sources(
    db: DB,
    status: SourceStatus | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
):
    query = select(Source).order_by(Source.id)
    if status is not None:
        query = query.where(Source.status == status)
    return db.scalars(query.offset(offset).limit(limit)).all()


@app.get("/sources/{source_id}", response_model=SourceOut)
def get_source(source_id: int, db: DB):
    return require(db, Source, source_id)


@app.put("/sources/{source_id}", response_model=SourceOut)
def update_source(source_id: int, payload: SourceInput, db: DB):
    try:
        source = lock_draft_source(db, source_id, "edit")
        normalized_url = payload.normalized_url
        ensure_unique_source_url(db, normalized_url, exclude_id=source_id)
        source.label = payload.label
        source.url = payload.url
        source.normalized_url = normalized_url
        source.excerpt = payload.excerpt
        return save_source(db, source)
    except Exception:
        db.rollback()
        raise


@app.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: int, db: DB):
    db.delete(require(db, Source, source_id))
    db.commit()
    return Response(status_code=204)


@app.post("/sources/{source_id}/discard", response_model=SourceOut)
def discard_source(source_id: int, db: DB):
    try:
        source = lock_draft_source(db, source_id, "discard")
        source.status = "discarded"
        return save(db, source)
    except Exception:
        db.rollback()
        raise


@app.post("/sources/{source_id}/approve", response_model=SourceApproveOut, status_code=201)
def approve_source(source_id: int, payload: SourceApproveInput, db: DB, clock: Clock):
    try:
        source = lock_draft_source(db, source_id, "approve")
        require(db, Deck, payload.deck_id)
        today = normalize_utc(clock()).date()
        card = Card(
            deck_id=payload.deck_id,
            front=payload.front,
            back=payload.back,
            kind=payload.kind,
            source_label=source.label,
            due_date=today,
        )
        source.status = "approved"
        db.add(card)
        db.flush()
        result = SourceApproveOut(
            source=SourceOut.model_validate(source),
            card=CardOut.model_validate(card),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result
