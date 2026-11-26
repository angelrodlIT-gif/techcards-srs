import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, get_engine
from app.main import app
from app.models import Base, Card, Deck, ErrorLog, Review
from app.personal_data import delete_errors, delete_reviews

NOW = datetime(2026, 2, 1, tzinfo=UTC)
OLD = datetime(2026, 1, 1, tzinfo=UTC)
ERROR = {"attempted": "I debug yesterday", "corrected": "I debugged yesterday", "rationale": "Past"}


def create(client, path, **payload):
    response = client.post(path, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def export(client):
    response = client.get("/personal-data/export")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].startswith("attachment;")
    snapshot = response.json()
    assert snapshot["format_version"] == 1
    return snapshot["data"]


def test_export_and_selective_deletion(client, set_clock):
    set_clock(NOW)
    deck = create(client, "/decks", name="Práctica")
    other_deck = create(client, "/decks", name="Keep this")
    source = create(client, "/sources", label="Shared label", excerpt="Example excerpt")
    card = create(
        client, f"/sources/{source['id']}/approve", deck_id=deck["id"], front="Q", back="A"
    )["card"]
    unlinked = create(
        client,
        "/cards",
        deck_id=other_deck["id"],
        front="Keep",
        back="Me",
        source_label=source["label"],
    )
    review = create(client, "/reviews", card_id=card["id"], quality=4)
    error = create(client, "/errors/suggest", answer=ERROR["attempted"], consent=True)["error"]
    derived = create(client, f"/errors/{error['id']}/approve", deck_id=deck["id"])["card"]
    derived_review = create(client, "/reviews", card_id=derived["id"], quality=5)

    data = export(client)
    assert set(data) == {"decks", "cards", "reviews", "sources", "error_logs"}
    assert data["decks"] == [deck, other_deck]
    assert data["sources"][0]["excerpt"] == "Example excerpt"
    assert data["cards"][0]["source_id"] == source["id"]
    assert data["cards"][1]["source_id"] is None
    assert [row["id"] for row in data["reviews"]] == [review["id"], derived_review["id"]]
    assert datetime.fromisoformat(data["reviews"][0]["reviewed_at"]) == NOW
    assert data["error_logs"][0]["card_id"] == derived["id"]
    assert data["error_logs"][0]["attempted"] == ERROR["attempted"]
    assert datetime.fromisoformat(data["error_logs"][0]["created_at"]) == NOW

    assert client.delete(f"/personal-data/sources/{source['id']}").status_code == 204
    assert client.get(f"/cards/{card['id']}").status_code == 404
    assert client.get(f"/cards/{unlinked['id']}").status_code == 200
    assert [row["id"] for row in export(client)["reviews"]] == [derived_review["id"]]
    assert client.delete(f"/personal-data/error_logs/{error['id']}").status_code == 204
    assert client.delete(f"/personal-data/error_logs/{error['id']}").status_code == 404
    assert client.get(f"/cards/{derived['id']}").status_code == 404
    assert export(client)["error_logs"] == export(client)["reviews"] == []


def test_retention_strict_cutoff_and_legacy_error(client, db_engine, set_clock):
    set_clock(OLD)
    deck = create(client, "/decks", name="Retention")
    card = create(client, "/cards", deck_id=deck["id"], front="Keep", back="Both")
    create(client, "/reviews", card_id=card["id"], quality=4)
    error = create(client, "/errors", **ERROR)
    derived = create(client, f"/errors/{error['id']}/approve", deck_id=deck["id"])["card"]
    with Session(db_engine) as db, db.begin():
        db.add(ErrorLog(**ERROR, status="draft"))

    set_clock(NOW)
    new = create(client, "/reviews", card_id=card["id"], quality=5)
    create(client, "/reviews", card_id=derived["id"], quality=5)
    create(client, "/errors", **ERROR)
    before = export(client)
    for collection in ("reviews", "error_logs"):
        payload = {"collection": collection, "before": "2026-02-01T01:00:00+01:00"}
        preview = client.post("/personal-data/retention", json=payload)
        assert preview.status_code == 200
        assert preview.json()["matched"] == 1
        assert preview.json()["applied"] is False
        assert export(client) == before
        applied = client.post("/personal-data/retention", json={**payload, "apply": True})
        assert applied.status_code == 200
        assert applied.json()["matched"] == 1
        assert applied.json()["applied"] is True
        assert client.post("/personal-data/retention", json=payload).json()["matched"] == 0
        before = export(client)

    assert [row["id"] for row in before["cards"]] == [card["id"]]
    assert [row["id"] for row in before["reviews"]] == [new["id"]]
    assert before["cards"][0]["repetitions"] == new["repetitions"]
    assert len(before["error_logs"]) == 2
    assert before["error_logs"][0]["created_at"] is None
    assert datetime.fromisoformat(before["error_logs"][1]["created_at"]) == NOW

    assert client.delete(f"/personal-data/reviews/{new['id']}").status_code == 204
    assert client.get(f"/cards/{card['id']}").json()["repetitions"] == new["repetitions"]
    assert client.delete(f"/personal-data/decks/{deck['id']}").status_code == 204
    assert export(client)["cards"] == []


def test_retention_rejects_ambiguous_requests(client):
    for change in (
        {"before": "2026-02-01T00:00:00"},
        {"before": 1770000000},
        {"collection": "decks"},
        {"apply": "false"},
        {"typo": True},
    ):
        payload = {"collection": "reviews", "before": NOW.isoformat(), **change}
        assert client.post("/personal-data/retention", json=payload).status_code == 422


def test_personal_data_migration_preserves_legacy_rows(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'personal_data.db'}"
    engine = create_engine(db_url)
    config = Config("alembic.ini")
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    try:
        command.upgrade(config, "0005")
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO decks VALUES (1, 'Legacy', '')"))
            connection.execute(
                text(
                    "INSERT INTO cards (id, deck_id, front, back, kind, repetitions, "
                    "interval_days, ease_factor, due_date) "
                    "VALUES (1, 1, 'Q', 'A', 'vocabulary', 0, 0, 2.5, '2026-02-01')"
                )
            )
            connection.execute(
                text("INSERT INTO error_logs VALUES (1, 'Q', 'A', 'Legacy', 'approved', 1)")
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT front, source_id FROM cards")).one() == (
                "Q",
                None,
            )
            assert connection.execute(text("SELECT card_id, created_at FROM error_logs")).one() == (
                1,
                None,
            )
        assert len(inspect(engine).get_check_constraints("cards")) == 1
        command.downgrade(config, "0005")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT card_id FROM error_logs")) == 1
            assert connection.scalar(text("SELECT front FROM cards")) == "Q"
        assert len(inspect(engine).get_check_constraints("cards")) == 1
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_personal_data_migration_cleans_legacy_sqlite_orphans(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'legacy_orphans.db'}"
    engine = create_engine(db_url)
    config = Config("alembic.ini")
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        command.upgrade(config, "0005")
        with engine.begin() as connection:
            # Simulate a pre-0006 SQLite DB where deck 2 and card 3 were deleted
            # without PRAGMA foreign_keys=ON, leaving orphaned children and links.
            connection.execute(text("INSERT INTO decks VALUES (1, 'Valid', '')"))
            connection.execute(
                text(
                    "INSERT INTO cards (id, deck_id, front, back, kind, repetitions, "
                    "interval_days, ease_factor, due_date) VALUES "
                    "(1, 1, 'Valid Q', 'Valid A', 'vocabulary', 0, 0, 2.5, '2026-02-01'), "
                    "(2, 2, 'Orphan Q', 'Orphan A', 'vocabulary', 0, 0, 2.5, '2026-02-01')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO reviews (id, card_id, quality, reviewed_at, interval_days, "
                    "ease_factor, repetitions, due_date) VALUES "
                    "(1, 1, 4, '2026-02-01 00:00:00', 1, 2.5, 1, '2026-02-02'), "
                    "(2, 2, 4, '2026-02-01 00:00:00', 1, 2.5, 1, '2026-02-02'), "
                    "(3, 3, 4, '2026-02-01 00:00:00', 1, 2.5, 1, '2026-02-02')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO error_logs (id, attempted, corrected, rationale, status, card_id) "
                    "VALUES "
                    "(1, 'Valid', 'Valid', 'Keep link', 'approved', 1), "
                    "(2, 'Orphan card', 'Fixed', 'Deck deleted', 'approved', 2), "
                    "(3, 'Deleted card', 'Fixed', 'Card deleted', 'approved', 3)"
                )
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            assert connection.execute(text("SELECT id, deck_id, source_id FROM cards")).all() == [
                (1, 1, None)
            ]
            assert connection.execute(text("SELECT id, card_id FROM reviews")).all() == [(1, 1)]
            assert connection.execute(
                text("SELECT id, card_id FROM error_logs ORDER BY id")
            ).all() == [(1, 1), (2, None), (3, None)]

        # Reopen through get_engine() (which enables PRAGMA foreign_keys=ON) and verify
        # that reusing deleted deck/card IDs cannot attach or delete unrelated rows.
        app_engine = get_engine()
        previous_overrides = dict(app.dependency_overrides)

        def override_db():
            with Session(app_engine) as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        try:
            with TestClient(app) as api_client:
                reused_deck = create(api_client, "/decks", name="Reused Deck ID")
                assert reused_deck["id"] == 2
                assert api_client.get("/cards", params={"deck_id": 2}).json() == []

                reused_card = create(
                    api_client, "/cards", deck_id=reused_deck["id"], front="New Q", back="New A"
                )
                assert reused_card["id"] == 2

                # Deleting the legacy error log that used to point at card 2 must NOT
                # delete the new unrelated card that reused ID 2.
                assert api_client.delete("/personal-data/error_logs/2").status_code == 204
                assert api_client.get(f"/cards/{reused_card['id']}").status_code == 200
                assert api_client.delete("/personal-data/error_logs/3").status_code == 204
                assert api_client.get(f"/cards/{reused_card['id']}").status_code == 200
                assert api_client.get("/cards/1").status_code == 200
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous_overrides)
            app_engine.dispose()
    finally:
        engine.dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()


def _record_sql(db_engine, action):
    statements: list[str] = []

    def before_execute(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(" ".join(statement.upper().split()))

    event.listen(db_engine, "before_cursor_execute", before_execute)
    try:
        result = action()
    finally:
        event.remove(db_engine, "before_cursor_execute", before_execute)
    return result, statements


def _first_prefix(statements: list[str], prefix: str) -> int:
    for idx, sql in enumerate(statements):
        if sql.startswith(prefix):
            return idx
    raise AssertionError(f"Expected SQL starting with {prefix!r} in {statements!r}")


def test_deletion_and_retention_use_canonical_lock_order(client, db_engine, set_clock):
    set_clock(OLD)
    deck = create(client, "/decks", name="Lock Order")
    err1 = create(client, "/errors", **ERROR)
    card1 = create(client, f"/errors/{err1['id']}/approve", deck_id=deck["id"])["card"]
    create(client, "/reviews", card_id=card1["id"], quality=4)

    # Direct personal-data card deletion locks error_logs before cards, and cards before reviews.
    resp, stmts = _record_sql(
        db_engine, lambda: client.delete(f"/personal-data/cards/{card1['id']}")
    )
    assert resp.status_code == 204
    assert client.get(f"/cards/{card1['id']}").status_code == 404
    assert client.get(f"/errors/{err1['id']}").json()["card_id"] is None
    assert _first_prefix(stmts, "SELECT ERROR_LOGS.ID FROM ERROR_LOGS") < _first_prefix(
        stmts, "SELECT CARDS.ID FROM CARDS"
    )
    assert _first_prefix(stmts, "SELECT CARDS.ID FROM CARDS") < _first_prefix(
        stmts, "SELECT REVIEWS.ID FROM REVIEWS"
    )

    # Standard /cards/{id} deletion follows the exact same lock order.
    err2 = create(client, "/errors", **ERROR)
    card2 = create(client, f"/errors/{err2['id']}/approve", deck_id=deck["id"])["card"]
    create(client, "/reviews", card_id=card2["id"], quality=4)
    resp, stmts = _record_sql(db_engine, lambda: client.delete(f"/cards/{card2['id']}"))
    assert resp.status_code == 204
    assert client.get(f"/errors/{err2['id']}").json()["card_id"] is None
    assert _first_prefix(stmts, "SELECT ERROR_LOGS.ID FROM ERROR_LOGS") < _first_prefix(
        stmts, "SELECT CARDS.ID FROM CARDS"
    )
    assert _first_prefix(stmts, "SELECT CARDS.ID FROM CARDS") < _first_prefix(
        stmts, "SELECT REVIEWS.ID FROM REVIEWS"
    )

    # Error-log deletion locks error_logs before cards, and cards before reviews.
    err3 = create(client, "/errors", **ERROR)
    card3 = create(client, f"/errors/{err3['id']}/approve", deck_id=deck["id"])["card"]
    create(client, "/reviews", card_id=card3["id"], quality=5)
    resp, stmts = _record_sql(
        db_engine, lambda: client.delete(f"/personal-data/error_logs/{err3['id']}")
    )
    assert resp.status_code == 204
    assert client.get(f"/cards/{card3['id']}").status_code == 404
    assert _first_prefix(stmts, "SELECT ERROR_LOGS.ID, ERROR_LOGS.CARD_ID") < _first_prefix(
        stmts, "SELECT CARDS.ID FROM CARDS"
    )
    assert _first_prefix(stmts, "SELECT CARDS.ID FROM CARDS") < _first_prefix(
        stmts, "SELECT REVIEWS.ID FROM REVIEWS"
    )

    # Error-log retention locks error_logs in PK order before cards in PK order.
    err4 = create(client, "/errors", **ERROR)
    card4 = create(client, f"/errors/{err4['id']}/approve", deck_id=deck["id"])["card"]
    create(client, "/reviews", card_id=card4["id"], quality=5)
    resp, stmts = _record_sql(
        db_engine,
        lambda: client.post(
            "/personal-data/retention",
            json={"collection": "error_logs", "before": NOW.isoformat(), "apply": True},
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["matched"] == 3
    assert client.get(f"/cards/{card4['id']}").status_code == 404
    assert _first_prefix(stmts, "SELECT ERROR_LOGS.ID, ERROR_LOGS.CARD_ID") < _first_prefix(
        stmts, "SELECT CARDS.ID FROM CARDS"
    )
    assert _first_prefix(stmts, "SELECT CARDS.ID FROM CARDS") < _first_prefix(
        stmts, "SELECT REVIEWS.ID FROM REVIEWS"
    )
    assert any("FROM ERROR_LOGS" in s and "ORDER BY ERROR_LOGS.ID" in s for s in stmts)
    assert any("FROM CARDS" in s and "ORDER BY CARDS.ID" in s for s in stmts)

    # Deck deletion locks decks -> error_logs -> cards -> reviews.
    err5 = create(client, "/errors", **ERROR)
    card5 = create(client, f"/errors/{err5['id']}/approve", deck_id=deck["id"])["card"]
    create(client, "/reviews", card_id=card5["id"], quality=4)
    resp, stmts = _record_sql(
        db_engine, lambda: client.delete(f"/personal-data/decks/{deck['id']}")
    )
    assert resp.status_code == 204
    assert client.get(f"/errors/{err5['id']}").json()["card_id"] is None
    assert _first_prefix(stmts, "SELECT DECKS.ID FROM DECKS") < _first_prefix(
        stmts, "SELECT ERROR_LOGS.ID FROM ERROR_LOGS"
    )
    assert _first_prefix(stmts, "SELECT ERROR_LOGS.ID FROM ERROR_LOGS") < _first_prefix(
        stmts, "SELECT CARDS.ID FROM CARDS"
    )
    assert _first_prefix(stmts, "SELECT CARDS.ID FROM CARDS") < _first_prefix(
        stmts, "SELECT REVIEWS.ID FROM REVIEWS"
    )

    # Source deletion locks sources -> error_logs -> cards -> reviews.
    deck2 = create(client, "/decks", name="Source Lock Order")
    source = create(client, "/sources", label="Docs")
    source_card = create(
        client, f"/sources/{source['id']}/approve", deck_id=deck2["id"], front="Q", back="A"
    )["card"]
    create(client, "/reviews", card_id=source_card["id"], quality=4)
    resp, stmts = _record_sql(
        db_engine, lambda: client.delete(f"/personal-data/sources/{source['id']}")
    )
    assert resp.status_code == 204
    assert client.get(f"/cards/{source_card['id']}").status_code == 404
    assert _first_prefix(stmts, "SELECT SOURCES.ID FROM SOURCES") < _first_prefix(
        stmts, "SELECT ERROR_LOGS.ID FROM ERROR_LOGS"
    )
    assert _first_prefix(stmts, "SELECT ERROR_LOGS.ID FROM ERROR_LOGS") < _first_prefix(
        stmts, "SELECT CARDS.ID FROM CARDS"
    )
    assert _first_prefix(stmts, "SELECT CARDS.ID FROM CARDS") < _first_prefix(
        stmts, "SELECT REVIEWS.ID FROM REVIEWS"
    )


def test_postgres_concurrent_card_and_error_deletion_no_deadlock(client, db_engine, set_clock):
    if db_engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency test requires TEST_DATABASE_URL")

    set_clock(OLD)
    deck = create(client, "/decks", name="PG Concurrency")

    def run_coordinated_race(first_request, second_request):
        first_locked = threading.Event()
        second_attempting = threading.Event()
        release_first = threading.Event()
        first_tid: dict[str, int | None] = {"id": None}

        def after_execute(_conn, _cursor, statement, _params, _context, _executemany):
            sql = " ".join(statement.upper().split())
            if first_tid["id"] is None and "FROM ERROR_LOGS" in sql and "FOR UPDATE" in sql:
                first_tid["id"] = threading.get_ident()
                first_locked.set()
                assert release_first.wait(timeout=10)

        def before_execute(_conn, _cursor, statement, _params, _context, _executemany):
            sql = " ".join(statement.upper().split())
            tid = threading.get_ident()
            if (
                first_tid["id"] is not None
                and tid != first_tid["id"]
                and ("FOR UPDATE" in sql or "DELETE FROM CARDS" in sql)
            ):
                second_attempting.set()

        event.listen(db_engine, "after_cursor_execute", after_execute)
        event.listen(db_engine, "before_cursor_execute", before_execute)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:

                def run_first():
                    with TestClient(app, raise_server_exceptions=False) as tc:
                        return first_request(tc)

                def run_second():
                    with TestClient(app, raise_server_exceptions=False) as tc:
                        return second_request(tc)

                f1 = pool.submit(run_first)
                assert first_locked.wait(timeout=5)
                f2 = pool.submit(run_second)
                assert second_attempting.wait(timeout=5)
                release_first.set()
                return f1.result(timeout=10), f2.result(timeout=10)
        finally:
            release_first.set()
            event.remove(db_engine, "after_cursor_execute", after_execute)
            event.remove(db_engine, "before_cursor_execute", before_execute)

    # Case 1: Error-log deletion locks error_logs first while card deletion runs concurrently.
    err1 = create(client, "/errors", **ERROR)
    card1 = create(client, f"/errors/{err1['id']}/approve", deck_id=deck["id"])["card"]
    r_err, r_card = run_coordinated_race(
        lambda tc: tc.delete(f"/personal-data/error_logs/{err1['id']}"),
        lambda tc: tc.delete(f"/personal-data/cards/{card1['id']}"),
    )
    assert r_err.status_code == 204
    assert r_card.status_code == 404
    assert export(client)["cards"] == []
    assert export(client)["error_logs"] == []

    # Case 2: Card deletion locks error_logs first while error-log retention runs concurrently.
    err2 = create(client, "/errors", **ERROR)
    card2 = create(client, f"/errors/{err2['id']}/approve", deck_id=deck["id"])["card"]
    r_card2, r_ret = run_coordinated_race(
        lambda tc: tc.delete(f"/personal-data/cards/{card2['id']}"),
        lambda tc: tc.post(
            "/personal-data/retention",
            json={"collection": "error_logs", "before": NOW.isoformat(), "apply": True},
        ),
    )
    assert r_card2.status_code == 204
    assert r_ret.status_code == 200
    assert r_ret.json()["matched"] == 1
    assert export(client)["cards"] == []
    assert export(client)["error_logs"] == []


def test_sqlite_deletion_and_retention_hold_write_lock_before_select(tmp_path):
    db_path = tmp_path / "sqlite_toctou.db"
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    conn2 = sqlite3.connect(db_path, timeout=0.05)
    conn2.execute("PRAGMA foreign_keys=ON")
    try:
        with Session(engine) as db, db.begin():
            deck = Deck(name="SQLite Lock")
            db.add(deck)
            db.flush()
            card = Card(deck_id=deck.id, front="Q1", back="A1", due_date=OLD.date())
            derived = Card(deck_id=deck.id, front="Q2", back="A2", due_date=OLD.date())
            db.add_all([card, derived])
            db.flush()
            old_review = Review(
                card_id=card.id,
                quality=4,
                reviewed_at=OLD,
                interval_days=1,
                ease_factor=2.5,
                repetitions=1,
                due_date=OLD.date(),
            )
            old_error = ErrorLog(**ERROR, status="approved", card_id=derived.id, created_at=OLD)
            db.add_all([old_review, old_error])
            db.flush()
            deck_id = deck.id
            card_id = card.id
            derived_id = derived.id
            review_id = old_review.id
            error_id = old_error.id

        # 1. During delete_reviews, right after SELECT and before DELETE, a second SQLite
        # connection must be blocked from deleting & reusing the selected review ID.
        review_race_attempted = {"seen": False, "locked": False}

        def intercept_review_select(_conn, _cursor, statement, _params, _context, _executemany):
            sql = " ".join(statement.upper().split())
            if sql.startswith("SELECT REVIEWS.ID FROM REVIEWS"):
                review_race_attempted["seen"] = True
                try:
                    conn2.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
                    conn2.execute(
                        "INSERT INTO reviews "
                        "(id, card_id, quality, reviewed_at, interval_days, ease_factor, "
                        "repetitions, due_date) VALUES (?, ?, 5, ?, 1, 2.5, 1, ?)",
                        (review_id, card_id, NOW.isoformat(), NOW.date().isoformat()),
                    )
                    conn2.commit()
                except sqlite3.OperationalError as exc:
                    conn2.rollback()
                    assert "locked" in str(exc).lower()
                    review_race_attempted["locked"] = True

        event.listen(engine, "after_cursor_execute", intercept_review_select)
        try:
            with Session(engine) as db, db.begin():
                assert delete_reviews(db, Review.reviewed_at < NOW) == 1
        finally:
            event.remove(engine, "after_cursor_execute", intercept_review_select)

        assert review_race_attempted == {"seen": True, "locked": True}

        # Once committed, conn2 can write normally again.
        conn2.execute(
            "INSERT INTO reviews "
            "(id, card_id, quality, reviewed_at, interval_days, ease_factor, "
            "repetitions, due_date) VALUES (?, ?, 5, ?, 1, 2.5, 1, ?)",
            (review_id, card_id, NOW.isoformat(), NOW.date().isoformat()),
        )
        conn2.commit()

        # 2. During delete_errors, right after SELECT and before DELETE, a second SQLite
        # connection must be blocked from deleting & reusing the selected error/card IDs.
        error_race_attempted = {"seen": False, "locked": False}

        def intercept_error_select(_conn, _cursor, statement, _params, _context, _executemany):
            sql = " ".join(statement.upper().split())
            if sql.startswith("SELECT ERROR_LOGS.ID, ERROR_LOGS.CARD_ID FROM ERROR_LOGS"):
                error_race_attempted["seen"] = True
                try:
                    conn2.execute("DELETE FROM error_logs WHERE id = ?", (error_id,))
                    conn2.execute("DELETE FROM cards WHERE id = ?", (derived_id,))
                    conn2.execute(
                        "INSERT INTO cards "
                        "(id, deck_id, front, back, kind, repetitions, interval_days, "
                        "ease_factor, due_date) VALUES (?, ?, 'New', 'Card', 'vocabulary', "
                        "0, 0, 2.5, ?)",
                        (derived_id, deck_id, NOW.date().isoformat()),
                    )
                    conn2.commit()
                except sqlite3.OperationalError as exc:
                    conn2.rollback()
                    assert "locked" in str(exc).lower()
                    error_race_attempted["locked"] = True

        event.listen(engine, "after_cursor_execute", intercept_error_select)
        try:
            with Session(engine) as db, db.begin():
                assert delete_errors(db, ErrorLog.created_at < NOW) == 1
        finally:
            event.remove(engine, "after_cursor_execute", intercept_error_select)

        assert error_race_attempted == {"seen": True, "locked": True}

        # 3. Calling a deletion helper when the session already started a SQLite write
        # transaction must succeed without nesting BEGIN IMMEDIATE.
        with Session(engine) as db, db.begin():
            db.add(Deck(name="Already Writing"))
            db.flush()
            assert delete_reviews(db, Review.reviewed_at < NOW) == 0
    finally:
        conn2.close()
        engine.dispose()
