from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager, joinedload, selectinload

from app.db import get_db
from app.generator import CardGenerator, get_generator
from app.learning import LearningSummary, summarize_learning
from app.listening import AudioUnavailable, SynthesisLimitReached, listening_audio
from app.models import Card, Deck, ErrorLog, Review, Source
from app.pronunciation import (
    ALLOWED_RECORDING_TYPES,
    MAX_RECORDING_BYTES,
    PRONUNCIATION_KINDS,
    RECORDING_TTL_SECONDS,
    build_pronunciation_comparison,
    pronunciation_recordings,
)
from app.remediation import STAR_PREFIX, build_remediation_draft
from app.schemas import (
    MAX_LISTENING_CHARS,
    CardInput,
    CardOut,
    DeckInput,
    DeckOut,
    ErrorApproveInput,
    ErrorApproveOut,
    ErrorExportCardOut,
    ErrorExportItemOut,
    ErrorExportOut,
    ErrorLogInput,
    ErrorLogOut,
    ErrorStatus,
    ErrorSuggestionInput,
    ErrorSuggestionOut,
    GenerateInput,
    Kind,
    PronunciationCompareInput,
    PronunciationCompareOut,
    PronunciationRecordingOut,
    RecordingStatus,
    ReviewInput,
    ReviewOut,
    SourceApproveInput,
    SourceApproveOut,
    SourceInput,
    SourceOut,
    SourceStatus,
    StudyCardPrompt,
    StudyCardReveal,
    StudyGradeInput,
    StudyTemplateOut,
    SuggestedCardOut,
    TemplateCardInput,
)
from app.sm2 import Schedule, schedule_review
from app.templates import STUDY_TEMPLATES, TEMPLATES_BY_ID


def utc_now() -> datetime:
    return datetime.now(UTC)


def get_clock() -> Callable[[], datetime]:
    return utc_now


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        yield
    finally:
        pronunciation_recordings.clear()


app = FastAPI(title="TechCards SRS", version="0.1.0", lifespan=lifespan)
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
    pronunciation_recordings.delete_deck(deck_id)
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
        .options(selectinload(Card.error_log))
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
    query = select(Card).options(selectinload(Card.error_log)).order_by(Card.id)
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
    previous = (card.deck_id, card.kind, card.back)
    for key, value in payload.model_dump().items():
        setattr(card, key, value)
    updated = save(db, card)
    if (updated.deck_id, updated.kind, updated.back) != previous:
        pronunciation_recordings.delete(card_id)
    return updated


@app.delete("/cards/{card_id}", status_code=204)
def delete_card(card_id: int, db: DB):
    db.delete(require(db, Card, card_id))
    db.commit()
    pronunciation_recordings.delete(card_id)
    return Response(status_code=204)


def record_review(
    db: Session, card_id: int, quality: int, clock: Callable[[], datetime]
) -> ReviewOut:
    # PostgreSQL serializes reviews for the same card; SQLite is for sequential unit tests.
    try:
        card = db.scalar(select(Card).where(Card.id == card_id).with_for_update())
        if card is None:
            raise HTTPException(404, "Card not found")
        now = normalize_utc(clock())
        result = schedule_review(
            Schedule(card.repetitions, card.interval_days, card.ease_factor),
            quality,
            now.date(),
        )
        card.repetitions = result.schedule.repetitions
        card.interval_days = result.schedule.interval_days
        card.ease_factor = result.schedule.ease_factor
        card.due_date = result.due_date
        review = Review(
            card_id=card.id,
            quality=quality,
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


@app.post("/reviews", response_model=ReviewOut, status_code=201)
def create_review(payload: ReviewInput, db: DB, clock: Clock):
    return record_review(db, payload.card_id, payload.quality, clock)


@app.get("/analytics/learning", response_model=LearningSummary)
def learning_summary(db: DB, start: date | None = None, end: date | None = None):
    if start is not None and end is not None and start > end:
        raise HTTPException(422, "start must be on or before end")
    return summarize_learning(db, start, end)


@app.get(
    "/study/next",
    response_model=StudyCardPrompt,
    responses={204: {"description": "No card due today"}},
)
def study_next(
    db: DB,
    clock: Clock,
    deck_id: int = Query(gt=0),
    kind: Kind | None = None,
    remediation_only: bool = Query(False),
):
    require(db, Deck, deck_id)
    today = normalize_utc(clock()).date()
    query = select(Card)
    query = query.join(Card.error_log) if remediation_only else query.outerjoin(Card.error_log)
    query = query.options(contains_eager(Card.error_log)).where(
        Card.deck_id == deck_id, Card.due_date <= today
    )
    if kind is not None:
        query = query.where(Card.kind == kind)
    card = db.scalar(query.order_by(Card.due_date, Card.id).limit(1))
    if card is None:
        return Response(status_code=204)
    return StudyCardPrompt(
        card_id=card.id,
        deck_id=card.deck_id,
        front=card.front,
        kind=card.kind,
        source_label=card.source_label,
        error_id=card.error_id,
        due_date=card.due_date,
        repetitions=card.repetitions,
        interval_days=card.interval_days,
        ease_factor=card.ease_factor,
    )


def require_loopback(request: Request, detail: str) -> None:
    if (
        request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
        or request.url.hostname not in {"127.0.0.1", "::1", "localhost"}
        or "forwarded" in request.headers
        or "x-forwarded-for" in request.headers
    ):
        raise HTTPException(403, detail)


def require_pronunciation_card(db: Session, card_id: int) -> Card:
    card = require(db, Card, card_id)
    if card.kind not in PRONUNCIATION_KINDS or not 1 <= len(card.back) <= MAX_LISTENING_CHARS:
        raise HTTPException(409, "Card is ineligible for pronunciation practice")
    return card


# Register this static path before /study/{card_id}/...
@app.delete("/study/pronunciation/recordings", status_code=204)
def clear_pronunciation_recordings(request: Request):
    require_loopback(request, "Pronunciation practice requires a direct loopback connection")
    pronunciation_recordings.clear()
    return Response(status_code=204)


@app.post("/study/{card_id}/reveal", response_model=StudyCardReveal)
def study_reveal(card_id: int, db: DB):
    card = require(db, Card, card_id)
    return StudyCardReveal(
        card_id=card.id,
        deck_id=card.deck_id,
        back=card.back,
        accepted_answers=card.accepted_answers,
        explanation=card.explanation,
    )


@app.post(
    "/study/{card_id}/audio",
    response_class=Response,
    responses={
        200: {"content": {"audio/mpeg": {"schema": {"type": "string", "format": "binary"}}}},
        403: {"description": "Audio requires a direct loopback connection"},
        404: {"description": "Card not found"},
        409: {"description": "Card is ineligible for listening audio"},
        429: {"description": "Synthesis budget exhausted"},
        503: {"description": "Audio unavailable. Use the reveal endpoint for text-only study."},
    },
)
def study_audio(
    card_id: int, db: DB, request: Request, polly_opt_in: Annotated[Literal["true"], Header()]
):
    require_loopback(request, "Listening audio requires a direct loopback connection")
    card = require(db, Card, card_id)
    if card.kind != "listening" or not 1 <= len(card.back) <= MAX_LISTENING_CHARS:
        raise HTTPException(409, "Card is ineligible for listening audio")
    try:
        audio = listening_audio.get(card.back)
    except SynthesisLimitReached as exc:
        raise HTTPException(429, "Synthesis budget exhausted. Reveal for the transcript.") from exc
    except AudioUnavailable as exc:
        raise HTTPException(503, "Audio unavailable. Reveal for the transcript.") from exc
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@app.post(
    "/study/{card_id}/pronunciation/audio",
    response_class=Response,
    responses={
        200: {"content": {"audio/mpeg": {"schema": {"type": "string", "format": "binary"}}}},
        403: {"description": "Pronunciation audio requires a direct loopback connection"},
        404: {"description": "Card not found"},
        409: {"description": "Card is ineligible for pronunciation practice"},
        429: {"description": "Synthesis budget exhausted"},
        503: {
            "description": (
                "Audio unavailable. Use /pronunciation/compare or /reveal for text-only practice."
            )
        },
    },
)
def study_pronunciation_audio(
    card_id: int, db: DB, request: Request, polly_opt_in: Annotated[Literal["true"], Header()]
):
    require_loopback(request, "Pronunciation audio requires a direct loopback connection")
    card = require_pronunciation_card(db, card_id)
    try:
        audio = listening_audio.get(card.back)
    except SynthesisLimitReached as exc:
        raise HTTPException(
            429,
            "Synthesis budget exhausted. Use /pronunciation/compare or /reveal for text-only "
            "practice.",
        ) from exc
    except AudioUnavailable as exc:
        raise HTTPException(
            503,
            "Audio unavailable. Use /pronunciation/compare or /reveal for text-only practice.",
        ) from exc
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@app.post(
    "/study/{card_id}/pronunciation/recording",
    response_model=PronunciationRecordingOut,
    status_code=201,
)
async def upload_pronunciation_recording(
    card_id: int,
    db: DB,
    request: Request,
    recording_consent: Annotated[Literal["true"], Header()],
):
    require_loopback(request, "Pronunciation practice requires a direct loopback connection")
    with pronunciation_recordings.track_upload(card_id) as upload_token:
        initial_card = require_pronunciation_card(db, card_id)
        initial_state = (initial_card.deck_id, initial_card.kind, initial_card.back)
        pronunciation_recordings.bind_upload_deck(upload_token, initial_card.deck_id)
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type not in ALLOWED_RECORDING_TYPES:
            raise HTTPException(415, "Unsupported recording media type")
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_RECORDING_BYTES:
                raise HTTPException(413, "Recording exceeds 512 KiB limit")
            chunks.append(chunk)
        if total == 0:
            raise HTTPException(422, "Recording audio must not be empty")
        audio = b"".join(chunks)
        db.expire_all()
        fresh_card = require_pronunciation_card(db, card_id)
        if (fresh_card.deck_id, fresh_card.kind, fresh_card.back) != initial_state:
            raise HTTPException(409, "Card changed during recording upload; retry recording")
        stored = pronunciation_recordings.put(
            fresh_card.id,
            fresh_card.deck_id,
            fresh_card.kind,
            fresh_card.back,
            media_type,
            audio,
            upload_token=upload_token,
        )
        if not stored:
            raise HTTPException(409, "Card changed during recording upload; retry recording")
    return PronunciationRecordingOut(
        card_id=fresh_card.id,
        media_type=media_type,
        size_bytes=total,
        expires_in_seconds=RECORDING_TTL_SECONDS,
    )


@app.get(
    "/study/{card_id}/pronunciation/recording",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            }
        },
        403: {"description": "Pronunciation practice requires a direct loopback connection"},
        404: {"description": "Card or recording not found"},
        409: {"description": "Card is ineligible for pronunciation practice"},
    },
)
def get_pronunciation_recording(card_id: int, db: DB, request: Request):
    require_loopback(request, "Pronunciation practice requires a direct loopback connection")
    card = require_pronunciation_card(db, card_id)
    stored = pronunciation_recordings.get(card.id, card.deck_id, card.kind, card.back)
    if stored is None:
        raise HTTPException(404, "Recording not found")
    media_type, audio = stored
    return Response(audio, media_type=media_type, headers={"Cache-Control": "no-store"})


@app.delete("/study/{card_id}/pronunciation/recording", status_code=204)
def delete_pronunciation_recording(card_id: int, db: DB, request: Request):
    require_loopback(request, "Pronunciation practice requires a direct loopback connection")
    pronunciation_recordings.delete(card_id)
    require(db, Card, card_id)
    return Response(status_code=204)


@app.post("/study/{card_id}/pronunciation/compare", response_model=PronunciationCompareOut)
def compare_pronunciation(
    card_id: int,
    db: DB,
    request: Request,
    payload: Annotated[PronunciationCompareInput | None, Body()] = None,
):
    require_loopback(request, "Pronunciation practice requires a direct loopback connection")
    card = require_pronunciation_card(db, card_id)
    body = payload or PronunciationCompareInput()
    has_recording = (
        pronunciation_recordings.get(card.id, card.deck_id, card.kind, card.back) is not None
    )
    if body.microphone_available:
        if not has_recording and body.spoken_transcript is None:
            raise HTTPException(
                409,
                "No active recording for this card. Record an attempt first or set "
                "microphone_available=false for the microphone-denied fallback.",
            )
        recording_status: RecordingStatus = "recorded" if has_recording else "transcript_only"
    else:
        recording_status = "microphone_denied_fallback"
    return build_pronunciation_comparison(
        card_id=card.id,
        deck_id=card.deck_id,
        kind=card.kind,
        reference_text=card.back,
        card_explanation=card.explanation,
        has_recording=has_recording,
        recording_status=recording_status,
        spoken_transcript=body.spoken_transcript,
        learner_notes=body.learner_notes,
    )


@app.post("/study/{card_id}/grade", response_model=ReviewOut, status_code=201)
def study_grade(card_id: int, payload: StudyGradeInput, db: DB, clock: Clock):
    return record_review(db, card_id, payload.quality, clock)


def require_template(template_id: str):
    template = TEMPLATES_BY_ID.get(template_id)
    if template is None:
        raise HTTPException(404, "Template not found")
    return template


@app.get("/templates", response_model=list[StudyTemplateOut])
def list_templates():
    return STUDY_TEMPLATES


@app.get("/templates/{template_id}", response_model=StudyTemplateOut)
def get_template(template_id: str):
    return require_template(template_id)


@app.post("/templates/{template_id}/cards", response_model=CardOut, status_code=201)
def create_card_from_template(template_id: str, payload: TemplateCardInput, db: DB, clock: Clock):
    template = require_template(template_id)
    require(db, Deck, payload.deck_id)
    today = normalize_utc(clock()).date()
    card = Card(
        deck_id=payload.deck_id,
        front=template.front,
        back=template.back,
        kind=template.kind,
        source_label=f"template:{template.id}",
        explanation=template.explanation,
        due_date=today,
    )
    return save(db, card)


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
    attempted_url = source.normalized_url
    try:
        return save(db, source)
    except IntegrityError as exc:
        db.rollback()
        if attempted_url is not None:
            raise HTTPException(409, "A source with this URL already exists") from exc
        raise


def lock_draft(db: Session, model, identifier: int, action: str, label: str):
    row = db.scalar(select(model).where(model.id == identifier).with_for_update())
    if row is None:
        raise HTTPException(404, f"{model.__name__} not found")
    if row.status != "draft":
        raise HTTPException(409, f"Cannot {action} {label} in '{row.status}' status")
    return row


def lock_draft_source(db: Session, source_id: int, action: str) -> Source:
    return lock_draft(db, Source, source_id, action, "source")


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
            accepted_answers=payload.accepted_answers,
            explanation=payload.explanation,
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


@app.post("/errors", response_model=ErrorLogOut, status_code=201)
def create_error(payload: ErrorLogInput, db: DB):
    return save(db, ErrorLog(**payload.model_dump(), status="draft"))


@app.get("/errors", response_model=list[ErrorLogOut])
def list_errors(
    db: DB,
    status: ErrorStatus | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
):
    query = select(ErrorLog).order_by(ErrorLog.id)
    if status is not None:
        query = query.where(ErrorLog.status == status)
    return db.scalars(query.offset(offset).limit(limit)).all()


# Register static paths before /errors/{error_id}.
@app.post("/errors/suggest", response_model=ErrorSuggestionOut, status_code=201)
def suggest_error(payload: ErrorSuggestionInput, db: DB):
    try:
        draft = build_remediation_draft(
            answer=payload.answer,
            prompt=payload.prompt,
            category=payload.category,
            corrected=payload.corrected,
            rationale=payload.rationale,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    err = save(
        db,
        ErrorLog(
            attempted=draft.attempted,
            corrected=draft.corrected,
            rationale=draft.rationale,
            status="draft",
        ),
    )
    return ErrorSuggestionOut(
        error=ErrorLogOut.model_validate(err),
        suggested_card=SuggestedCardOut(
            front=f"Correct: {draft.attempted}",
            back=draft.corrected,
            kind=draft.suggested_kind,
            explanation=draft.rationale,
        ),
    )


@app.get("/errors/export", response_model=ErrorExportOut)
def export_errors(
    db: DB,
    clock: Clock,
    status: ErrorStatus | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    query = select(ErrorLog).options(joinedload(ErrorLog.card)).order_by(ErrorLog.id)
    if status is not None:
        query = query.where(ErrorLog.status == status)
    rows = db.scalars(query.offset(offset).limit(limit)).all()
    items = [
        ErrorExportItemOut(
            id=row.id,
            attempted=row.attempted,
            corrected=row.corrected,
            rationale=row.rationale,
            status=row.status,
            card_id=row.card.id if row.card is not None else None,
            card=ErrorExportCardOut.model_validate(row.card) if row.card is not None else None,
        )
        for row in rows
    ]
    return ErrorExportOut(exported_at=normalize_utc(clock()), count=len(items), items=items)


@app.get("/errors/{error_id}", response_model=ErrorLogOut)
def get_error(error_id: int, db: DB):
    return require(db, ErrorLog, error_id)


@app.put("/errors/{error_id}", response_model=ErrorLogOut)
def update_error(error_id: int, payload: ErrorLogInput, db: DB):
    try:
        err = lock_draft(db, ErrorLog, error_id, "edit", "error")
        err.attempted = payload.attempted
        err.corrected = payload.corrected
        err.rationale = payload.rationale
        return save(db, err)
    except Exception:
        db.rollback()
        raise


@app.delete("/errors/{error_id}", status_code=204)
def delete_error(error_id: int, db: DB, delete_card: bool = Query(False)):
    deleted_card_id: int | None = None
    try:
        err = db.scalar(select(ErrorLog).where(ErrorLog.id == error_id).with_for_update())
        if err is None:
            raise HTTPException(404, "ErrorLog not found")
        card_id = err.card_id
        db.delete(err)
        if delete_card and card_id is not None:
            db.flush()
            card = db.scalar(select(Card).where(Card.id == card_id).with_for_update())
            if card is not None:
                db.delete(card)
                deleted_card_id = card_id
        db.commit()
    except Exception:
        db.rollback()
        raise
    if deleted_card_id is not None:
        pronunciation_recordings.delete(deleted_card_id)
    return Response(status_code=204)


@app.post("/errors/{error_id}/discard", response_model=ErrorLogOut)
def discard_error(error_id: int, db: DB):
    try:
        err = lock_draft(db, ErrorLog, error_id, "discard", "error")
        err.status = "discarded"
        return save(db, err)
    except Exception:
        db.rollback()
        raise


@app.post("/errors/{error_id}/approve", response_model=ErrorApproveOut, status_code=201)
def approve_error(error_id: int, payload: ErrorApproveInput, db: DB, clock: Clock):
    try:
        err = lock_draft(db, ErrorLog, error_id, "approve", "error")
        require(db, Deck, payload.deck_id)
        front = payload.front if payload.front is not None else f"Correct: {err.attempted}"
        back = payload.back if payload.back is not None else err.corrected
        kind = (
            payload.kind
            if "kind" in payload.model_fields_set
            else ("behavioral" if err.rationale.startswith(STAR_PREFIX) else payload.kind)
        )
        explanation = (
            payload.explanation if "explanation" in payload.model_fields_set else err.rationale
        )
        try:
            card_input = CardInput(
                deck_id=payload.deck_id,
                front=front,
                back=back,
                kind=kind,
                source_label=f"error:{err.id}",
                accepted_answers=payload.accepted_answers,
                explanation=explanation,
            )
        except ValidationError as exc:
            raise HTTPException(422, "; ".join(e["msg"] for e in exc.errors())) from exc
        today = normalize_utc(clock()).date()
        card = Card(**card_input.model_dump(), due_date=today)
        err.status = "approved"
        err.card = card
        db.add(card)
        db.flush()
        result = ErrorApproveOut(
            error=ErrorLogOut.model_validate(err),
            card=CardOut.model_validate(card),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result
