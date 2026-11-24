from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Card
from app.schemas import CardOut


def create_deck(client):
    resp = client.post("/decks", json={"name": "Practice Formats"})
    assert resp.status_code == 201
    return resp.json()["id"]


def schedule_of(card):
    return (card["repetitions"], card["interval_days"], card["ease_factor"], card["due_date"])


def test_new_practice_formats_crud_and_existing_kinds(client, set_clock):
    set_clock(datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC))
    did = create_deck(client)

    samples = [
        (
            "sentence",
            "The deployment failed because the health check timed out.",
            "timed out",
            ["  exceeded timeout  ", "", "   ", "Timed out", "timed out"],
            "  Used when a request stops waiting.  ",
            ["exceeded timeout", "Timed out", "timed out"],
            "Used when a request stops waiting.",
        ),
        (
            "cloze",
            "We need to ____ the database connection pool.",
            "drain",
            ["flush", "flush", "Flush"],
            "Drain lets in-flight queries finish.",
            ["flush", "Flush"],
            "Drain lets in-flight queries finish.",
        ),
        (
            "es_en",
            "Necesitamos revertir el despliegue por latencia.",
            "We need to roll back the deployment due to latency.",
            ["We need to revert the deployment due to latency."],
            "'Roll back' is standard for undoing a release.",
            ["We need to revert the deployment due to latency."],
            "'Roll back' is standard for undoing a release.",
        ),
    ]
    ids = []
    for kind, front, back, alts, exp, exp_alts, exp_note in samples:
        resp = client.post(
            "/cards",
            json={
                "deck_id": did,
                "front": front,
                "back": back,
                "kind": kind,
                "accepted_answers": alts,
                "explanation": exp,
            },
        )
        assert resp.status_code == 201
        cid = resp.json()["id"]
        ids.append(cid)
        got = client.get(f"/cards/{cid}").json()
        assert (got["kind"], got["accepted_answers"], got["explanation"]) == (
            kind,
            exp_alts,
            exp_note,
        )

    for existing_kind in ("vocabulary", "interview_phrase", "behavioral"):
        resp = client.post(
            "/cards",
            json={
                "deck_id": did,
                "front": f"Prompt {existing_kind}",
                "back": "Primary",
                "kind": existing_kind,
                "accepted_answers": ["Alt"],
                "explanation": "Note",
            },
        )
        assert resp.status_code == 201
        assert (resp.json()["accepted_answers"], resp.json()["explanation"]) == (["Alt"], "Note")

    # Review once, then edit new fields via PUT and confirm schedule stays intact.
    cid = ids[0]
    assert client.post("/reviews", json={"card_id": cid, "quality": 5}).status_code == 201
    expected_schedule = (1, 1, 2.6, "2026-05-02")

    updated = client.put(
        f"/cards/{cid}",
        json={
            "deck_id": did,
            "front": "The worker ____ after three retries.",
            "back": "backed off",
            "kind": "cloze",
            "accepted_answers": ["paused"],
            "explanation": "Replaced explanation.",
        },
    )
    assert updated.status_code == 200
    assert (updated.json()["kind"], updated.json()["accepted_answers"]) == ("cloze", ["paused"])
    assert updated.json()["explanation"] == "Replaced explanation."
    assert schedule_of(updated.json()) == expected_schedule

    # Omitting optional fields on PUT resets accepted_answers to [] and explanation to None.
    cleared = client.put(
        f"/cards/{cid}",
        json={"deck_id": did, "front": "Retry policy?", "back": "Exponential backoff"},
    )
    assert cleared.status_code == 200
    assert (cleared.json()["kind"], cleared.json()["accepted_answers"]) == ("vocabulary", [])
    assert cleared.json()["explanation"] is None
    assert schedule_of(cleared.json()) == expected_schedule


@pytest.mark.parametrize(
    "front",
    [
        "No blank in this sentence.",
        "Only ___ three underscores.",
        "Too many _____ underscores.",
        "Two ____ blanks in ____ one card.",
        "Adjacent ________ underscores.",
        "One ____ and one _____ blank.",
    ],
)
def test_cloze_rejects_invalid_blank_counts(client, front):
    did = create_deck(client)
    resp = client.post(
        "/cards", json={"deck_id": did, "front": front, "back": "word", "kind": "cloze"}
    )
    assert resp.status_code == 422


def test_cloze_valid_with_identifiers_and_put_validation(client):
    did = create_deck(client)
    valid = client.post(
        "/cards",
        json={
            "deck_id": did,
            "front": "Set max_connections in __init__ to ____ before load testing.",
            "back": "100",
            "kind": "cloze",
        },
    )
    assert valid.status_code == 201
    cid = valid.json()["id"]
    bad_put = client.put(
        f"/cards/{cid}",
        json={"deck_id": did, "front": "No blank anymore", "back": "100", "kind": "cloze"},
    )
    assert bad_put.status_code == 422
    assert "____" in client.get(f"/cards/{cid}").json()["front"]


def test_accepted_answers_and_explanation_validation(client):
    did = create_deck(client)

    blank = client.post(
        "/cards",
        json={
            "deck_id": did,
            "front": "A",
            "back": "B",
            "accepted_answers": ["", "   \t\n "],
            "explanation": "   \t\n ",
        },
    )
    assert blank.status_code == 201
    assert (blank.json()["accepted_answers"], blank.json()["explanation"]) == ([], None)

    at_limit = client.post(
        "/cards",
        json={
            "deck_id": did,
            "front": "Boundaries",
            "back": "Primary",
            "accepted_answers": [f"alt-{i}" for i in range(19)] + [f"  {'x' * 5000}  "],
            "explanation": f"  {'y' * 5000}  ",
        },
    )
    assert at_limit.status_code == 201
    assert (len(at_limit.json()["accepted_answers"]), len(at_limit.json()["explanation"])) == (
        20,
        5000,
    )

    invalid_payloads = [
        {"accepted_answers": [f"alt-{i}" for i in range(21)]},
        {"accepted_answers": ["x" * 5001]},
        {"accepted_answers": ["ok\x00bad"]},
        {"accepted_answers": ["  \x00  "]},
        {"accepted_answers": None},
        {"accepted_answers": "not-a-list"},
        {"accepted_answers": [123]},
        {"accepted_answers": [None]},
        {"explanation": "y" * 5001},
        {"explanation": "bad\x00note"},
        {"explanation": "  \x00  "},
        {"explanation": 123},
    ]
    for extra in invalid_payloads:
        resp = client.post("/cards", json={"deck_id": did, "front": "Q", "back": "A", **extra})
        assert resp.status_code == 422, f"Expected 422 for {extra!r}"


def test_source_approve_and_generate_behavior(client, set_clock):
    set_clock(datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC))
    did = create_deck(client)

    src = client.post("/sources", json={"label": "RFC Notes"}).json()
    for bad in (
        {"deck_id": did, "front": "Missing blank", "back": "retry", "kind": "cloze"},
        {"deck_id": did, "front": "Q", "back": "A", "accepted_answers": ["a\x00b"]},
        {"deck_id": did, "front": "Q", "back": "A", "explanation": "a\x00b"},
    ):
        assert client.post(f"/sources/{src['id']}/approve", json=bad).status_code == 422
    assert client.get(f"/sources/{src['id']}").json()["status"] == "draft"

    approved = client.post(
        f"/sources/{src['id']}/approve",
        json={
            "deck_id": did,
            "front": "Idempotent requests can be ____ safely.",
            "back": "retried",
            "kind": "cloze",
            "accepted_answers": ["  replayed  ", ""],
            "explanation": "  Safe against duplicate delivery.  ",
        },
    )
    assert approved.status_code == 201
    card = approved.json()["card"]
    assert (card["kind"], card["source_label"], card["accepted_answers"], card["explanation"]) == (
        "cloze",
        "RFC Notes",
        ["replayed"],
        "Safe against duplicate delivery.",
    )
    assert schedule_of(card) == (0, 0, 2.5, "2026-05-01")

    generated = client.post(
        "/cards/generate",
        json={"deck_id": did, "text": "AWS Python PostgreSQL troubleshooting", "max_cards": 6},
    )
    assert generated.status_code == 201
    assert {c["kind"] for c in generated.json()} == {"vocabulary", "interview_phrase", "behavioral"}
    assert all(c["accepted_answers"] == [] and c["explanation"] is None for c in generated.json())


def test_scheduling_unchanged_across_practice_formats(client, set_clock):
    set_clock(datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC))
    did = create_deck(client)
    defs = [
        ("vocabulary", "VPC?", "Virtual Private Cloud"),
        ("sentence", "The job failed due to memory pressure.", "memory pressure"),
        ("cloze", "Enable ____ scaling for burst traffic.", "horizontal"),
        ("es_en", "Reducir el tiempo de respuesta", "Reduce response time"),
    ]
    cards = {
        kind: client.post(
            "/cards", json={"deck_id": did, "front": front, "back": back, "kind": kind}
        ).json()["id"]
        for kind, front, back in defs
    }
    for review_time, quality in (
        (datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC), 5),
        (datetime(2026, 6, 2, 10, 0, 0, tzinfo=UTC), 4),
        (datetime(2026, 6, 8, 10, 0, 0, tzinfo=UTC), 0),
    ):
        set_clock(review_time)
        schedules = {}
        for kind, cid in cards.items():
            assert (
                client.post("/reviews", json={"card_id": cid, "quality": quality}).status_code
                == 201
            )
            schedules[kind] = schedule_of(client.get(f"/cards/{cid}").json())
        assert (
            schedules["sentence"]
            == schedules["cloze"]
            == schedules["es_en"]
            == schedules["vocabulary"]
        )


def test_legacy_null_and_nul_fields_remain_readable(client, db_engine):
    did = create_deck(client)
    with Session(db_engine) as session:
        legacy_null = Card(
            deck_id=did, front="Legacy Q", back="Legacy A", accepted_answers=None, explanation=None
        )
        session.add(legacy_null)
        session.commit()
        null_id = legacy_null.id

    got = client.get(f"/cards/{null_id}")
    assert got.status_code == 200
    assert (got.json()["accepted_answers"], got.json()["explanation"]) == ([], None)
    assert [c["accepted_answers"] for c in client.get("/cards").json()] == [[]]
    assert [c["accepted_answers"] for c in client.get(f"/decks/{did}/due").json()] == [[]]

    if db_engine.dialect.name == "sqlite":
        with Session(db_engine) as session:
            legacy_nul = Card(
                deck_id=did,
                front="Old\x00Front",
                back="Old\x00Back",
                accepted_answers=["Alt\x00One"],
                explanation="Note\x00Here",
            )
            session.add(legacy_nul)
            session.commit()
            nul_id = legacy_nul.id
        resp = client.get(f"/cards/{nul_id}")
        assert resp.status_code == 200
        assert (resp.json()["accepted_answers"], resp.json()["explanation"]) == (
            ["Alt\x00One"],
            "Note\x00Here",
        )


def test_card_practice_formats_migration_round_trip(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / 'formats_migration.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()

    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "migrations"))
    engine = create_engine(db_url)
    try:
        command.upgrade(cfg, "0003")
        pre_cols = {c["name"] for c in inspect(engine).get_columns("cards")}
        assert "accepted_answers" not in pre_cols and "explanation" not in pre_cols
        with engine.begin() as conn:
            conn.execute(sa_text("INSERT INTO decks (id, name, description) VALUES (1, 'D', '')"))
            conn.execute(
                sa_text(
                    "INSERT INTO cards (id, deck_id, front, back, kind, source_label, "
                    "repetitions, interval_days, ease_factor, due_date) "
                    "VALUES (1, 1, 'Q', 'A', 'vocabulary', 'M1', 2, 6, 2.6, '2026-05-10')"
                )
            )

        command.upgrade(cfg, "head")
        cols = {c["name"]: c for c in inspect(engine).get_columns("cards")}
        assert cols["accepted_answers"]["nullable"] and cols["explanation"]["nullable"]
        with Session(engine) as session:
            card = session.get(Card, 1)
            assert card is not None and (card.accepted_answers, card.explanation) == (None, None)
            serialized = CardOut.model_validate(card)
            assert (serialized.accepted_answers, serialized.explanation) == ([], None)
            assert schedule_of(serialized.model_dump(mode="json")) == (2, 6, 2.6, "2026-05-10")
            card.accepted_answers, card.explanation = ["Alt A"], "Why A works."
            session.commit()

        command.downgrade(cfg, "0003")
        down_cols = {c["name"] for c in inspect(engine).get_columns("cards")}
        assert "accepted_answers" not in down_cols and "explanation" not in down_cols
        with engine.connect() as conn:
            row = conn.execute(
                sa_text(
                    "SELECT front, back, kind, source_label, repetitions, interval_days, "
                    "ease_factor, due_date FROM cards WHERE id = 1"
                )
            ).one()
            assert tuple(row) == ("Q", "A", "vocabulary", "M1", 2, 6, 2.6, "2026-05-10")

        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            row = conn.execute(
                sa_text("SELECT accepted_answers, explanation FROM cards WHERE id = 1")
            ).one()
            assert tuple(row) == (None, None)
    finally:
        engine.dispose()
        monkeypatch.undo()
        get_settings.cache_clear()
