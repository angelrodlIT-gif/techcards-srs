from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.generator import CardGenerator, get_generator
from app.models import Card, Deck, Review
from app.schemas import (
    CardInput,
    CardOut,
    DeckInput,
    DeckOut,
    GenerateInput,
    ReviewInput,
    ReviewOut,
)
from app.sm2 import Schedule, schedule_review

app = FastAPI(title="TechCards SRS", version="0.1.0")
DB = Annotated[Session, Depends(get_db)]
Generator = Annotated[CardGenerator, Depends(get_generator)]


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
    deck_id: int, db: DB, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)
):
    require(db, Deck, deck_id)
    return db.scalars(
        select(Card)
        .where(Card.deck_id == deck_id, Card.due_date <= datetime.now(UTC).date())
        .order_by(Card.due_date, Card.id)
        .offset(offset)
        .limit(limit)
    ).all()


# Register this static path before /cards/{card_id}.
@app.post("/cards/generate", response_model=list[CardOut], status_code=201)
def generate_cards(payload: GenerateInput, db: DB, generator: Generator):
    require(db, Deck, payload.deck_id)
    generated = generator.generate(payload.text, payload.max_cards)
    # Validate provider output before any rows are persisted.
    cards = [
        Card(
            **CardInput(
                deck_id=payload.deck_id, front=c.front, back=c.back, kind=c.kind
            ).model_dump()
        )
        for c in generated[: payload.max_cards]
    ]
    db.add_all(cards)
    db.commit()
    for card in cards:
        db.refresh(card)
    return cards


@app.post("/cards", response_model=CardOut, status_code=201)
def create_card(payload: CardInput, db: DB):
    require(db, Deck, payload.deck_id)
    return save(db, Card(**payload.model_dump()))


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
def create_review(payload: ReviewInput, db: DB):
    # PostgreSQL serializes reviews for the same card; SQLite is for sequential unit tests.
    card = db.scalar(select(Card).where(Card.id == payload.card_id).with_for_update())
    if card is None:
        raise HTTPException(404, "Card not found")
    now = datetime.now(UTC)
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
    return save(db, review)
