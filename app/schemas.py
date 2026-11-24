import re
from datetime import date, datetime
from ipaddress import IPv6Address
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


def reject_nul(value: str) -> str:
    if "\x00" in value:
        raise ValueError("value must not contain NUL bytes")
    return value


NoNul = AfterValidator(reject_nul)
Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000), NoNul
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
SourceLabel = Annotated[str, StringConstraints(min_length=1, max_length=255)]
RequiredSourceLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255), NoNul
]
SourceUrl = Annotated[str, StringConstraints(min_length=1, max_length=2048), NoNul]
MAX_SOURCE_URL_CHARS = 2048
MAX_SOURCE_URL_UTF8_BYTES = 2048
Excerpt = Annotated[str, StringConstraints(min_length=1, max_length=20000), NoNul]
Explanation = Annotated[str, StringConstraints(min_length=1, max_length=5000), NoNul]
MAX_ACCEPTED_ANSWERS = 20
MAX_ACCEPTED_ANSWER_CHARS = 5000
CLOZE_BLANK_RE = re.compile(r"_{4,}")
Kind = Literal["vocabulary", "interview_phrase", "behavioral", "sentence", "cloze", "es_en"]
SourceStatus = Literal["draft", "approved", "discarded"]


def normalize_source_url(raw: str) -> tuple[str, str]:
    trimmed = raw.strip()
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in trimmed):
        raise ValueError("url must not contain whitespace or control characters")
    parsed = urlsplit(trimmed)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("url must be an absolute http or https URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("url must not include credentials")
    port = parsed.port
    if port is not None and not (1 <= port <= 65535):
        raise ValueError("url has an invalid port")

    is_default = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    if parsed.netloc.startswith("["):
        try:
            IPv6Address(parsed.hostname)
        except ValueError as exc:
            raise ValueError("url has an unsupported bracketed host literal") from exc
        host = f"[{parsed.hostname}]"
    else:
        host = parsed.hostname
    netloc = host if (port is None or is_default) else f"{host}:{port}"
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    normalized = urlunsplit((scheme, netloc, path, parsed.query, ""))
    if len(trimmed) > MAX_SOURCE_URL_CHARS:
        raise ValueError(f"url must be at most {MAX_SOURCE_URL_CHARS} characters")
    if len(normalized.encode("utf-8")) > MAX_SOURCE_URL_UTF8_BYTES:
        raise ValueError(f"normalized url must be at most {MAX_SOURCE_URL_UTF8_BYTES} UTF-8 bytes")
    return trimmed, normalized


class DeckInput(BaseModel):
    name: Name
    description: str = Field(default="", max_length=5000)


class DeckOut(DeckInput):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CardPayloadBase(BaseModel):
    deck_id: int = Field(gt=0)
    front: Text
    back: Text
    kind: Kind = "vocabulary"
    accepted_answers: list[str] = Field(default_factory=list, max_length=MAX_ACCEPTED_ANSWERS)
    explanation: Explanation | None = None

    @field_validator("accepted_answers", mode="after")
    @classmethod
    def normalize_accepted_answers(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            reject_nul(item)
            stripped = item.strip()
            if not stripped:
                continue
            if len(stripped) > MAX_ACCEPTED_ANSWER_CHARS:
                raise ValueError(
                    f"accepted answer must be at most {MAX_ACCEPTED_ANSWER_CHARS} characters"
                )
            if stripped not in seen:
                seen.add(stripped)
                cleaned.append(stripped)
        return cleaned

    @field_validator("explanation", mode="before")
    @classmethod
    def normalize_explanation(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def validate_cloze_front(self) -> Self:
        if self.kind == "cloze" and CLOZE_BLANK_RE.findall(self.front) != ["____"]:
            raise ValueError("cloze card front must contain exactly one '____' blank")
        return self


class CardInput(CardPayloadBase):
    source_label: SourceLabel | None = None

    @field_validator("source_label", mode="before")
    @classmethod
    def normalize_source_label(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    deck_id: int
    front: str
    back: str
    kind: Kind
    source_label: str | None
    accepted_answers: list[str] = Field(default_factory=list)
    explanation: str | None = None
    id: int
    repetitions: int
    interval_days: int
    ease_factor: float
    due_date: date

    @field_validator("accepted_answers", mode="before")
    @classmethod
    def default_null_accepted_answers(cls, value: object) -> object:
        return [] if value is None else value


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


class SourceInput(BaseModel):
    label: RequiredSourceLabel
    url: SourceUrl | None = None
    excerpt: Excerpt | None = None

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            trimmed, _ = normalize_source_url(stripped)
            return trimmed
        return value

    @field_validator("excerpt", mode="before")
    @classmethod
    def normalize_excerpt(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @property
    def normalized_url(self) -> str | None:
        return normalize_source_url(self.url)[1] if self.url is not None else None


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    url: str | None
    normalized_url: str | None
    excerpt: str | None
    status: SourceStatus


class SourceApproveInput(CardPayloadBase):
    pass


class SourceApproveOut(BaseModel):
    source: SourceOut
    card: CardOut
