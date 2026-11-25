from datetime import UTC, datetime

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ErrorLog

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
