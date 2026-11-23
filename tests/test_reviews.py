import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

import app.main as main_module
from app.main import app
from app.models import Card, Review
from app.sm2 import Schedule, schedule_review


def _create_deck_and_card(client: TestClient) -> tuple[int, int]:
    deck = client.post("/decks", json={"name": "SRS Hardening"})
    assert deck.status_code == 201
    deck_id = deck.json()["id"]
    card = client.post("/cards", json={"deck_id": deck_id, "front": "ACID?", "back": "Atomicity"})
    assert card.status_code == 201
    return deck_id, card.json()["id"]


def _snapshot(db_engine, card_id: int) -> tuple[tuple, list[tuple]]:
    with Session(db_engine) as session:
        card = session.get(Card, card_id)
        assert card is not None
        card_state = (card.repetitions, card.interval_days, card.ease_factor, card.due_date)
        reviews = session.scalars(
            select(Review).where(Review.card_id == card_id).order_by(Review.id)
        ).all()
        rows = [
            (r.id, r.quality, r.repetitions, r.interval_days, r.ease_factor, r.due_date)
            for r in reviews
        ]
    return card_state, rows


def _review_fields(resp) -> tuple[int, int, str]:
    body = resp.json()
    return body["repetitions"], body["interval_days"], body["due_date"]


def _require_postgres(db_engine) -> None:
    if db_engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency test requires TEST_DATABASE_URL")


def test_utc_midnight_due_and_review_boundaries(client, set_clock):
    set_clock(datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC))
    deck_id, card_id = _create_deck_and_card(client)
    assert client.get(f"/cards/{card_id}").json()["due_date"] == "2026-01-01"
    assert [c["id"] for c in client.get(f"/decks/{deck_id}/due").json()] == [card_id]

    first = client.post("/reviews", json={"card_id": card_id, "quality": 5})
    assert first.status_code == 201
    assert _review_fields(first) == (1, 1, "2026-01-02")
    assert datetime.fromisoformat(first.json()["reviewed_at"]) == datetime(
        2026, 1, 1, 23, 59, 59, tzinfo=UTC
    )
    assert client.get(f"/decks/{deck_id}/due").json() == []

    # Crossing UTC midnight by 1 second makes the card due immediately.
    set_clock(datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC))
    assert [c["id"] for c in client.get(f"/decks/{deck_id}/due").json()] == [card_id]

    second = client.post("/reviews", json={"card_id": card_id, "quality": 5})
    assert second.status_code == 201
    assert _review_fields(second) == (2, 6, "2026-01-08")

    set_clock(datetime(2026, 1, 7, 23, 59, 59, tzinfo=UTC))
    assert client.get(f"/decks/{deck_id}/due").json() == []
    set_clock(datetime(2026, 1, 8, 0, 0, 0, tzinfo=UTC))
    assert [c["id"] for c in client.get(f"/decks/{deck_id}/due").json()] == [card_id]


def test_non_utc_offset_normalizes_to_utc_and_naive_rejected(client, db_engine, set_clock):
    # 2026-01-01 20:00:00-05:00 equals 2026-01-02 01:00:00 UTC.
    set_clock(datetime(2026, 1, 1, 20, 0, 0, tzinfo=timezone(timedelta(hours=-5))))
    _, card_id = _create_deck_and_card(client)
    assert client.get(f"/cards/{card_id}").json()["due_date"] == "2026-01-02"

    review = client.post("/reviews", json={"card_id": card_id, "quality": 4})
    assert review.status_code == 201
    assert review.json()["due_date"] == "2026-01-03"
    assert datetime.fromisoformat(review.json()["reviewed_at"]) == datetime(
        2026, 1, 2, 1, 0, 0, tzinfo=UTC
    )
    before = _snapshot(db_engine, card_id)

    set_clock(datetime(2026, 1, 3, 12, 0, 0))
    with TestClient(app, raise_server_exceptions=False) as err_client:
        resp = err_client.post("/reviews", json={"card_id": card_id, "quality": 4})
    assert resp.status_code == 500
    assert _snapshot(db_engine, card_id) == before


def test_early_repeated_failed_and_overdue_submissions(client, db_engine, set_clock):
    set_clock(datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC))
    deck_id, card_id = _create_deck_and_card(client)

    r1 = client.post("/reviews", json={"card_id": card_id, "quality": 5})
    assert r1.status_code == 201 and _review_fields(r1) == (1, 1, "2026-01-02")

    # Identical repeated submission on the same day is accepted and NOT idempotent.
    r2 = client.post("/reviews", json={"card_id": card_id, "quality": 5})
    assert r2.status_code == 201 and r2.json()["id"] != r1.json()["id"]
    assert _review_fields(r2) == (2, 6, "2026-01-07")

    # Early submission (4 days before due_date) schedules from the review date.
    set_clock(datetime(2026, 1, 3, 10, 0, 0, tzinfo=UTC))
    r3 = client.post("/reviews", json={"card_id": card_id, "quality": 4})
    assert r3.status_code == 201 and _review_fields(r3) == (3, 17, "2026-01-20")

    # Failed review resets repetitions and schedules due_date to tomorrow UTC.
    r4 = client.post("/reviews", json={"card_id": card_id, "quality": 1})
    assert r4.status_code == 201 and _review_fields(r4) == (0, 1, "2026-01-04")
    assert client.get(f"/decks/{deck_id}/due").json() == []

    # Overdue submission (6 days late) is due and schedules from the review date.
    set_clock(datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC))
    assert [c["id"] for c in client.get(f"/decks/{deck_id}/due").json()] == [card_id]
    r5 = client.post("/reviews", json={"card_id": card_id, "quality": 4})
    assert r5.status_code == 201 and _review_fields(r5) == (1, 1, "2026-01-11")

    card_state, rows = _snapshot(db_engine, card_id)
    assert len(rows) == 5
    assert card_state == rows[-1][2:]


def test_failed_scheduling_rolls_back_atomically(client, db_engine, monkeypatch):
    _, card_id = _create_deck_and_card(client)
    before = _snapshot(db_engine, card_id)

    monkeypatch.setattr(
        main_module,
        "schedule_review",
        lambda *_a, **_kw: (_ for _ in ()).throw(ValueError("corrupted scheduling state")),
    )
    with TestClient(app, raise_server_exceptions=False) as err_client:
        assert (
            err_client.post("/reviews", json={"card_id": card_id, "quality": 4}).status_code == 500
        )
    assert _snapshot(db_engine, card_id) == before

    monkeypatch.undo()
    recovery = client.post("/reviews", json={"card_id": card_id, "quality": 4})
    assert recovery.status_code == 201 and recovery.json()["repetitions"] == 1


def test_review_insert_failure_rolls_back_card_update(client, db_engine):
    _, card_id = _create_deck_and_card(client)
    before = _snapshot(db_engine, card_id)
    card_update_seen = False

    def fail_on_review_insert(_conn, _cursor, statement, _params, _context, _executemany):
        nonlocal card_update_seen
        sql = statement.upper()
        if "UPDATE CARDS" in sql:
            card_update_seen = True
        if "INSERT INTO REVIEWS" in sql:
            raise RuntimeError("injected review insert failure")

    event.listen(db_engine, "before_cursor_execute", fail_on_review_insert)
    try:
        with TestClient(app, raise_server_exceptions=False) as err_client:
            resp = err_client.post("/reviews", json={"card_id": card_id, "quality": 5})
    finally:
        event.remove(db_engine, "before_cursor_execute", fail_on_review_insert)

    assert card_update_seen and resp.status_code == 500
    assert _snapshot(db_engine, card_id) == before

    recovery = client.post("/reviews", json={"card_id": card_id, "quality": 5})
    assert recovery.status_code == 201 and recovery.json()["repetitions"] == 1


def test_commit_failure_rolls_back_card_and_review(client, db_engine, monkeypatch):
    _, card_id = _create_deck_and_card(client)
    before = _snapshot(db_engine, card_id)
    original_commit = Session.commit
    armed = {"fail": True}

    def flaky_commit(self):
        if armed["fail"]:
            armed["fail"] = False
            raise RuntimeError("injected commit failure")
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", flaky_commit)
    with TestClient(app, raise_server_exceptions=False) as err_client:
        resp = err_client.post("/reviews", json={"card_id": card_id, "quality": 5})
    assert resp.status_code == 500
    assert _snapshot(db_engine, card_id) == before


def test_postgres_concurrent_reviews_serialize_atomically(client, db_engine, monkeypatch):
    _require_postgres(db_engine)
    _, card_id = _create_deck_and_card(client)

    first_locked, release_first, second_entered = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    calls, calls_lock = {"n": 0}, threading.Lock()
    real_schedule = main_module.schedule_review

    def coordinated_schedule(state, quality, reviewed_on):
        with calls_lock:
            calls["n"] += 1
            n = calls["n"]
        if n == 1:
            first_locked.set()
            assert release_first.wait(timeout=10)
        else:
            second_entered.set()
        return real_schedule(state, quality, reviewed_on)

    monkeypatch.setattr(main_module, "schedule_review", coordinated_schedule)

    def submit():
        with TestClient(app) as tc:
            return tc.post("/reviews", json={"card_id": card_id, "quality": 5})

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(submit)
        assert first_locked.wait(timeout=5)
        f2 = pool.submit(submit)
        assert not second_entered.wait(timeout=0.25)
        release_first.set()
        r1, r2 = f1.result(timeout=10), f2.result(timeout=10)

    assert (r1.status_code, r2.status_code) == (201, 201)
    card_state, rows = _snapshot(db_engine, card_id)
    assert [(r[2], r[3], r[4]) for r in rows] == [(1, 1, 2.6), (2, 6, 2.7)]
    assert card_state == rows[-1][2:]


def test_postgres_concurrent_peer_failure_rolls_back_cleanly(client, db_engine, monkeypatch):
    _require_postgres(db_engine)
    _, card_id = _create_deck_and_card(client)

    first_locked, release_first = threading.Event(), threading.Event()
    second_waiting, second_entered = threading.Event(), threading.Event()
    first_tid: dict[str, int | None] = {"id": None}
    real_schedule = main_module.schedule_review

    def coordinated_schedule(state, quality, reviewed_on):
        if first_tid["id"] is None:
            first_tid["id"] = threading.get_ident()
            first_locked.set()
            assert release_first.wait(timeout=10)
        else:
            second_entered.set()
        return real_schedule(state, quality, reviewed_on)

    def on_sql(_conn, _cursor, statement, _params, _context, _executemany):
        sql, tid = statement.upper(), threading.get_ident()
        if "FOR UPDATE" in sql and first_tid["id"] is not None and tid != first_tid["id"]:
            second_waiting.set()
        if tid == first_tid["id"] and "INSERT INTO REVIEWS" in sql:
            raise RuntimeError("injected peer insert failure")

    monkeypatch.setattr(main_module, "schedule_review", coordinated_schedule)
    event.listen(db_engine, "before_cursor_execute", on_sql)

    def submit(quality: int):
        with TestClient(app, raise_server_exceptions=False) as tc:
            return tc.post("/reviews", json={"card_id": card_id, "quality": quality})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(submit, 5)
            assert first_locked.wait(timeout=5)
            f2 = pool.submit(submit, 4)
            assert second_waiting.wait(timeout=5)
            assert not second_entered.wait(timeout=0.1)
            release_first.set()
            r1, r2 = f1.result(timeout=10), f2.result(timeout=10)
    finally:
        event.remove(db_engine, "before_cursor_execute", on_sql)

    assert (r1.status_code, r2.status_code) == (500, 201)
    card_state, rows = _snapshot(db_engine, card_id)
    assert len(rows) == 1 and rows[0][1:5] == (4, 1, 1, 2.5)
    assert card_state == rows[0][2:]


def test_postgres_concurrent_burst_keeps_card_and_history_consistent(client, db_engine):
    _require_postgres(db_engine)
    _, card_id = _create_deck_and_card(client)

    qualities = [5, 4, 3, 2, 5, 4]
    barrier = threading.Barrier(len(qualities))

    def submit(quality: int):
        with TestClient(app) as tc:
            barrier.wait(timeout=10)
            return tc.post("/reviews", json={"card_id": card_id, "quality": quality})

    with ThreadPoolExecutor(max_workers=len(qualities)) as pool:
        responses = list(pool.map(submit, qualities))
    assert [r.status_code for r in responses] == [201] * len(qualities)

    with Session(db_engine) as session:
        card = session.get(Card, card_id)
        assert card is not None
        reviews = session.scalars(
            select(Review).where(Review.card_id == card_id).order_by(Review.id)
        ).all()

    assert len(reviews) == len(qualities)
    assert sorted(r.quality for r in reviews) == sorted(qualities)

    state = Schedule()
    for review in reviews:
        expected = schedule_review(state, review.quality, review.reviewed_at.astimezone(UTC).date())
        assert (review.repetitions, review.interval_days, review.ease_factor, review.due_date) == (
            expected.schedule.repetitions,
            expected.schedule.interval_days,
            expected.schedule.ease_factor,
            expected.due_date,
        )
        state = expected.schedule

    last = reviews[-1]
    assert (card.repetitions, card.interval_days, card.ease_factor, card.due_date) == (
        last.repetitions,
        last.interval_days,
        last.ease_factor,
        last.due_date,
    )
