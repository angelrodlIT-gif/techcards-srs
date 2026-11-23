from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy import text as sa_text

from app.config import get_settings
from app.generator import GeneratedCard, MockGenerator, get_generator
from app.main import app


def deck(client):
    response = client.post("/decks", json={"name": "Cloud English"})
    assert response.status_code == 201
    return response.json()["id"]


def test_crud_review_and_cascade(client):
    did = deck(client)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/decks").json()[0]["id"] == did
    assert client.put(f"/decks/{did}", json={"name": "AWS"}).json()["name"] == "AWS"
    assert client.get(f"/decks/{did}").json()["name"] == "AWS"
    card = client.post("/cards", json={"deck_id": did, "front": "API?", "back": "Interface"})
    assert card.status_code == 201
    cid = card.json()["id"]
    assert len(client.get(f"/decks/{did}/due").json()) == 1
    assert len(client.get("/cards", params={"deck_id": did}).json()) == 1
    assert client.get(f"/cards/{cid}").json()["repetitions"] == 0
    updated = client.put(f"/cards/{cid}", json={"deck_id": did, "front": "SQL?", "back": "Query"})
    assert updated.json()["front"] == "SQL?"
    review = client.post("/reviews", json={"card_id": cid, "quality": 5})
    assert review.status_code == 201
    assert review.json()["interval_days"] == 1
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    assert review.json()["due_date"] == tomorrow.isoformat()
    assert client.get(f"/decks/{did}/due").json() == []
    assert client.get(f"/cards/{cid}").json()["ease_factor"] == 2.6
    assert client.post("/reviews", json={"card_id": cid, "quality": 0}).json()["repetitions"] == 0
    assert client.delete(f"/decks/{did}").status_code == 204
    assert client.get(f"/cards/{cid}").status_code == 404
    assert client.post("/reviews", json={"card_id": cid, "quality": 3}).status_code == 404


def test_delete_card_and_missing_resources(client):
    did = deck(client)
    cid = client.post("/cards", json={"deck_id": did, "front": "A", "back": "B"}).json()["id"]
    assert client.delete(f"/cards/{cid}").status_code == 204
    for path in ["/cards/999", "/decks/999", "/decks/999/due"]:
        assert client.get(path).status_code == 404
    assert (
        client.post("/cards", json={"deck_id": 999, "front": "A", "back": "B"}).status_code == 404
    )
    assert (
        client.post("/cards/generate", json={"deck_id": 999, "text": "Python AWS job"}).status_code
        == 404
    )


def test_generation_is_deterministic_and_bounded(client):
    did = deck(client)
    payload = {"deck_id": did, "text": "AWS Python PostgreSQL troubleshooting", "max_cards": 6}
    first = client.post("/cards/generate", json=payload)
    second = client.post("/cards/generate", json=payload)
    assert first.status_code == 201

    def fields(cards):
        return [(c["front"], c["back"], c["kind"]) for c in cards]

    assert fields(first.json()) == fields(second.json())
    assert {c["kind"] for c in first.json()} == {"vocabulary", "interview_phrase", "behavioral"}
    assert len(client.post("/cards/generate", json={**payload, "max_cards": 1}).json()) == 1
    assert len(MockGenerator().generate("Unrecognized subject matter", 20)) == 2


def test_provider_is_replaceable(client):
    class FakeProvider:
        def generate(self, text, max_cards):
            return [GeneratedCard("Custom prompt", "Custom answer", "vocabulary")]

    app.dependency_overrides[get_generator] = FakeProvider
    result = client.post(
        "/cards/generate", json={"deck_id": deck(client), "text": "Any technical job"}
    )
    assert result.json()[0]["front"] == "Custom prompt"


@pytest.mark.parametrize("quality", [-1, 6, True, 2.5, "5"])
def test_invalid_review_quality(client, quality):
    assert client.post("/reviews", json={"card_id": 1, "quality": quality}).status_code == 422


def test_validation_and_pagination(client):
    assert client.post("/decks", json={"name": "   "}).status_code == 422
    did = deck(client)
    assert (
        client.post("/cards", json={"deck_id": did, "front": " ", "back": "B"}).status_code == 422
    )
    for text in ["short", "x" * 20001]:
        assert (
            client.post("/cards/generate", json={"deck_id": did, "text": text}).status_code == 422
        )
    assert client.get("/decks?limit=101").status_code == 422
    assert client.get("/decks?offset=1").json() == []


def test_card_source_label_crud_and_schedule_preservation(client, set_clock):
    set_clock(datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC))
    did = deck(client)

    unlabeled = client.post("/cards", json={"deck_id": did, "front": "DNS?", "back": "Names"})
    assert unlabeled.status_code == 201
    unlabeled_id = unlabeled.json()["id"]
    assert unlabeled.json()["source_label"] is None
    assert client.get(f"/cards/{unlabeled_id}").json()["source_label"] is None

    blank_label = client.post(
        "/cards",
        json={"deck_id": did, "front": "TCP?", "back": "Stream", "source_label": "   \t\n "},
    )
    assert blank_label.status_code == 201
    assert blank_label.json()["source_label"] is None
    assert client.get(f"/cards/{blank_label.json()['id']}").json()["source_label"] is None

    labeled = client.post(
        "/cards",
        json={
            "deck_id": did,
            "front": "IAM?",
            "back": "Access control",
            "source_label": "  AWS Support JD  ",
        },
    )
    assert labeled.status_code == 201
    cid = labeled.json()["id"]
    assert labeled.json()["source_label"] == "AWS Support JD"
    assert client.get(f"/cards/{cid}").json()["source_label"] == "AWS Support JD"

    listed = client.get("/cards", params={"deck_id": did}).json()
    by_id = {c["id"]: c["source_label"] for c in listed}
    assert by_id[unlabeled_id] is None
    assert by_id[cid] == "AWS Support JD"
    due_by_id = {c["id"]: c["source_label"] for c in client.get(f"/decks/{did}/due").json()}
    assert due_by_id[unlabeled_id] is None
    assert due_by_id[cid] == "AWS Support JD"

    # Advance scheduling to non-default values before editing source_label.
    review = client.post("/reviews", json={"card_id": cid, "quality": 5})
    assert review.status_code == 201
    expected_schedule = (1, 1, 2.6, "2026-05-02")

    def schedule_of(body):
        return (body["repetitions"], body["interval_days"], body["ease_factor"], body["due_date"])

    after_review = client.get(f"/cards/{cid}").json()
    assert after_review["source_label"] == "AWS Support JD"
    assert schedule_of(after_review) == expected_schedule

    # Update label with whitespace trimming; scheduling fields must stay unchanged.
    updated = client.put(
        f"/cards/{cid}",
        json={
            "deck_id": did,
            "front": "IAM roles?",
            "back": "Temporary credentials",
            "kind": "interview_phrase",
            "source_label": "  RFC 9110 / AWS Docs  ",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["source_label"] == "RFC 9110 / AWS Docs"
    assert schedule_of(updated.json()) == expected_schedule
    re_read = client.get(f"/cards/{cid}").json()
    assert re_read["source_label"] == "RFC 9110 / AWS Docs"
    assert schedule_of(re_read) == expected_schedule

    # Clear label via explicit null; scheduling fields must stay unchanged.
    cleared_null = client.put(
        f"/cards/{cid}",
        json={
            "deck_id": did,
            "front": "IAM roles?",
            "back": "Temporary credentials",
            "kind": "interview_phrase",
            "source_label": None,
        },
    )
    assert cleared_null.status_code == 200
    assert cleared_null.json()["source_label"] is None
    assert schedule_of(cleared_null.json()) == expected_schedule
    assert client.get(f"/cards/{cid}").json()["source_label"] is None

    # Set label again, then clear via blank string; scheduling fields must stay unchanged.
    client.put(
        f"/cards/{cid}",
        json={"deck_id": did, "front": "IAM?", "back": "Access", "source_label": "Blog"},
    )
    cleared_blank = client.put(
        f"/cards/{cid}",
        json={"deck_id": did, "front": "IAM?", "back": "Access", "source_label": "   "},
    )
    assert cleared_blank.status_code == 200
    assert cleared_blank.json()["source_label"] is None
    assert schedule_of(cleared_blank.json()) == expected_schedule

    # Set label again, then clear by omitting source_label on PUT.
    client.put(
        f"/cards/{cid}",
        json={"deck_id": did, "front": "IAM?", "back": "Access", "source_label": "Notes"},
    )
    cleared_omit = client.put(
        f"/cards/{cid}",
        json={"deck_id": did, "front": "IAM?", "back": "Access"},
    )
    assert cleared_omit.status_code == 200
    assert cleared_omit.json()["source_label"] is None
    assert schedule_of(cleared_omit.json()) == expected_schedule

    # Generated cards expose nullable source_label as null without requiring it in input.
    generated = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "AWS Python troubleshooting role", "max_cards": 2},
    )
    assert generated.status_code == 201
    assert [c["source_label"] for c in generated.json()] == [None, None]

    # Boundary and type validation for source_label.
    max_ok = client.post(
        "/cards",
        json={"deck_id": did, "front": "Len", "back": "255", "source_label": "x" * 255},
    )
    assert max_ok.status_code == 201
    assert max_ok.json()["source_label"] == "x" * 255
    assert (
        client.post(
            "/cards",
            json={"deck_id": did, "front": "Len", "back": "256", "source_label": "x" * 256},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/cards",
            json={"deck_id": did, "front": "Type", "back": "Bad", "source_label": 123},
        ).status_code
        == 422
    )


def test_card_source_label_migration_round_trip(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / 'migration_round_trip.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()

    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "migrations"))
    engine = create_engine(db_url)
    try:
        command.upgrade(cfg, "0001")
        assert "source_label" not in {c["name"] for c in inspect(engine).get_columns("cards")}

        with engine.begin() as conn:
            conn.execute(sa_text("INSERT INTO decks (id, name, description) VALUES (1, 'D', '')"))
            conn.execute(
                sa_text(
                    "INSERT INTO cards (id, deck_id, front, back, kind, "
                    "repetitions, interval_days, ease_factor, due_date) "
                    "VALUES (1, 1, 'Q', 'A', 'vocabulary', 2, 6, 2.6, '2026-05-10')"
                )
            )

        command.upgrade(cfg, "head")
        cols = {c["name"]: c for c in inspect(engine).get_columns("cards")}
        assert "source_label" in cols and cols["source_label"]["nullable"] is True
        with engine.begin() as conn:
            row = conn.execute(
                sa_text(
                    "SELECT source_label, repetitions, interval_days, ease_factor, due_date "
                    "FROM cards WHERE id = 1"
                )
            ).one()
            assert tuple(row) == (None, 2, 6, 2.6, "2026-05-10")
            conn.execute(sa_text("UPDATE cards SET source_label = 'AWS JD' WHERE id = 1"))

        command.downgrade(cfg, "0001")
        assert "source_label" not in {c["name"] for c in inspect(engine).get_columns("cards")}
        with engine.connect() as conn:
            row = conn.execute(
                sa_text(
                    "SELECT front, back, repetitions, interval_days, ease_factor, due_date "
                    "FROM cards WHERE id = 1"
                )
            ).one()
            assert tuple(row) == ("Q", "A", 2, 6, 2.6, "2026-05-10")

        command.upgrade(cfg, "head")
        cols = {c["name"]: c for c in inspect(engine).get_columns("cards")}
        assert "source_label" in cols and cols["source_label"]["nullable"] is True
        with engine.connect() as conn:
            label = conn.execute(
                sa_text("SELECT source_label FROM cards WHERE id = 1")
            ).scalar_one()
            assert label is None
    finally:
        engine.dispose()
        monkeypatch.undo()
        get_settings.cache_clear()
