from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Kind = Literal["vocabulary", "interview_phrase", "behavioral"]


class DeckInput(BaseModel):
    name: Name
    description: str = Field(default="", max_length=5000)


class DeckOut(DeckInput):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CardInput(BaseModel):
    deck_id: int = Field(gt=0)
    front: Text
    back: Text
    kind: Kind = "vocabulary"


class CardOut(CardInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    repetitions: int
    interval_days: int
    ease_factor: float
    due_date: date


class GenerateInput(BaseModel):
    deck_id: int = Field(gt=0)
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=20000)]
    max_cards: int = Field(default=6, ge=1, le=20)


class ReviewInput(BaseModel):
    card_id: int = Field(gt=0)
    quality: int = Field(strict=True, ge=0, le=5)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    card_id: int
    quality: int
    reviewed_at: datetime
    interval_days: int
    ease_factor: float
    repetitions: int
    due_date: date
