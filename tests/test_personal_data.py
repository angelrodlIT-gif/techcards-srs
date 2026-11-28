import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import get_settings
from app.db import get_engine
from app.main import app


def export(client):
    result = client.get("/personal-data/export")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    return result.json()["data"]


def erase(client, collection, row):
    return client.delete(
        f"/personal-data/{collection}/{row['id']}", params={"identity": row["identity"]}
    )


@pytest.mark.parametrize("collection", ["cards", "reviews", "sources"])
def test_saved_export_cannot_delete_successor(client, db_engine, collection):
    if db_engine.dialect.name != "sqlite":
        pytest.skip("SQLite reuses the highest deleted ID")
    deck = client.post("/decks", json={"name": "Test"}).json()
    card_input = {"deck_id": deck["id"], "front": "First", "back": "Answer"}
    if collection == "reviews":
        card = client.post("/cards", json=card_input).json()
        payload = {"card_id": card["id"], "quality": 4}
    elif collection == "cards":
        payload = card_input
    else:
        payload = {"label": "Source"}

    assert client.post(f"/{collection}", json=payload).status_code == 201
    old = export(client)[collection][0]
    assert erase(client, collection, old).status_code == 204
    assert client.post(f"/{collection}", json=payload).status_code == 201
    successor = export(client)[collection][0]
    assert successor["id"] == old["id"]
    assert successor["identity"] != old["identity"]
    assert erase(client, collection, old).status_code == 404
    assert export(client)[collection] == [successor]


def test_retention_selectively_removes_private_history(client, set_clock, caplog):
    deck = client.post("/decks", json={"name": "Test"}).json()
    card = client.post(
        "/cards", json={"deck_id": deck["id"], "front": "Question", "back": "Private example"}
    ).json()
    set_clock(datetime(2020, 1, 1, tzinfo=UTC))
    assert client.post("/reviews", json={"card_id": card["id"], "quality": 4}).status_code == 201
    set_clock(datetime(2022, 1, 1, tzinfo=UTC))
    assert client.post("/reviews", json={"card_id": card["id"], "quality": 4}).status_code == 201
    payload = {"collection": "reviews", "before": "2021-01-01T00:00:00Z"}
    before = export(client)
    assert client.post("/personal-data/retention", json=payload).json()["matched"] == 1
    assert export(client) == before
    assert (
        client.post("/personal-data/retention", json={**payload, "apply": True}).json()["matched"]
        == 1
    )
    assert export(client)["reviews"] == before["reviews"][1:]
    assert "Private example" not in caplog.text


@pytest.mark.parametrize("collection", ["sources", "error_logs"])
def test_delete_and_approval_serialize(client, db_engine, collection):
    if db_engine.url.database in (None, "", ":memory:"):
        pytest.skip("Concurrent requests need independent database connections")
    deck = client.post("/decks", json={"name": "Test"}).json()
    path = "/sources" if collection == "sources" else "/errors"
    payload = (
        {"label": "draft"}
        if collection == "sources"
        else {"attempted": "wrong", "corrected": "right", "rationale": "reason"}
    )
    row = client.post(path, json=payload).json()
    selected = export(client)[collection][0]
    if collection == "error_logs":
        assert (
            client.post(
                f"{path}/{row['id']}/approve",
                params={"identity": row["identity"]},
                json={"deck_id": deck["id"]},
            ).status_code
            == 201
        )
        row = client.post(path, json=payload).json()
    gate = Barrier(3)

    def approve():
        gate.wait(timeout=5)
        return client.post(
            f"{path}/{row['id']}/approve",
            params={"identity": row["identity"]},
            json={"deck_id": deck["id"], "front": "question", "back": "answer"},
        ).status_code

    def remove():
        gate.wait(timeout=5)
        if collection == "error_logs":
            response = client.post(
                "/personal-data/retention",
                json={"collection": collection, "before": "2099-01-01T00:00:00Z", "apply": True},
            )
            assert response.json()["matched"] == 2
            return response.status_code
        return erase(client, collection, selected).status_code

    def delete_deck():
        gate.wait(timeout=5)
        return client.delete(f"/decks/{deck['id']}").status_code

    with ThreadPoolExecutor(max_workers=3) as pool:
        operations = [pool.submit(operation) for operation in (approve, remove, delete_deck)]
        approved, removed, deck_removed = [operation.result(timeout=10) for operation in operations]
    assert approved in {201, 404}
    assert removed == (200 if collection == "error_logs" else 204)
    assert deck_removed == 204
    snapshot = export(client)
    assert snapshot["cards"] == snapshot[collection] == []


def test_sqlite_upgrade_detaches_reused_error_link_and_backup_preserves_export(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.db"
    restored = tmp_path / "restored.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{source}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "0006")
        with sqlite3.connect(source) as conn:
            conn.executescript("""
                INSERT INTO decks (id, name, description) VALUES (1, 'deck', '');
                INSERT INTO cards (id, deck_id, front, back, kind, repetitions,
                    interval_days, ease_factor, due_date)
                    VALUES (1, 1, 'old', 'old', 'vocabulary', 0, 0, 2.5, '2020-01-01');
                INSERT INTO error_logs (attempted, corrected, rationale, status, card_id)
                    VALUES ('old', 'right', 'reason', 'approved', 1);
                DELETE FROM cards WHERE id = 1;
                INSERT INTO cards (id, deck_id, front, back, kind, repetitions,
                    interval_days, ease_factor, due_date)
                    VALUES (1, 1, 'successor', 'answer', 'vocabulary', 0, 0, 2.5, '2020-01-01');
                """)
        command.upgrade(config, "head")
        with TestClient(app) as client:
            before = export(client)
            legacy = before["error_logs"][0]
            assert legacy["card_id"] is None
            assert legacy["created_at"] is None
        get_engine().dispose()
        with sqlite3.connect(source) as original, sqlite3.connect(restored) as target:
            original.backup(target)
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{restored}")
        get_settings.cache_clear()
        get_engine.cache_clear()
        with TestClient(app) as client:
            assert export(client) == before
            assert erase(client, "error_logs", legacy).status_code == 204
            assert export(client)["cards"] == before["cards"]
    finally:
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("path", "collection"), [("/sources", "sources"), ("/errors", "error_logs")]
)
def test_pending_approval_rejects_replacement(client, db_engine, monkeypatch, path, collection):
    if db_engine.dialect.name != "sqlite" or not db_engine.url.database:
        pytest.skip("Requires separate SQLite connections and ID reuse")
    deck = client.post("/decks", json={"name": "Deck"}).json()
    payload = (
        {"label": "Draft"}
        if collection == "sources"
        else {"attempted": "wrong", "corrected": "right", "rationale": "reason"}
    )
    original = client.post(path, json=payload).json()
    selected = export(client)[collection][0]
    approval_path = f"{path}/{original['id']}/approve"
    approval_payload = {"deck_id": deck["id"], "front": "Question", "back": "Answer"}
    assert client.post(approval_path, json=approval_payload).status_code == 422
    waiting, resume = Event(), Event()
    lock = main_module.lock_personal_write

    def wait_before_lock(db):
        waiting.set()
        assert resume.wait(timeout=5)
        lock(db)

    monkeypatch.setattr(main_module, "lock_personal_write", wait_before_lock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        approval = pool.submit(
            client.post,
            approval_path,
            params={"identity": selected["identity"]},
            json=approval_payload,
        )
        try:
            assert waiting.wait(timeout=5)
            assert erase(client, collection, selected).status_code == 204
            replacement = client.post(path, json=payload).json()
            assert replacement["id"] == original["id"]
            before = export(client)
        finally:
            resume.set()
        assert approval.result(timeout=5).status_code in {404, 409}
    assert export(client) == before
    assert before[collection][0]["status"] == "draft"
    assert before["cards"] == []


def test_sqlite_upgrade_preserves_cards_with_unverified_decks(tmp_path, monkeypatch):
    source = tmp_path / "legacy.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{source}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "0006")
        with sqlite3.connect(source) as conn:
            conn.executescript("""
                INSERT INTO decks (id, name, description) VALUES (1, 'old', ''), (2, 'missing', '');
                INSERT INTO cards (id, deck_id, front, back, kind, repetitions,
                    interval_days, ease_factor, due_date) VALUES
                    (1, 1, 'reused deck', 'answer', 'vocabulary', 0, 0, 2.5, '2020-01-01'),
                    (2, 2, 'orphan', 'answer', 'vocabulary', 0, 0, 2.5, '2020-01-01');
                INSERT INTO reviews (card_id, quality, reviewed_at, interval_days,
                    ease_factor, repetitions, due_date) VALUES
                    (1, 4, '2020-01-01', 1, 2.5, 1, '2020-01-02'),
                    (3, 3, '2020-01-01', 1, 2.5, 1, '2020-01-02');
                DELETE FROM decks;
                INSERT INTO decks (id, name, description) VALUES (1, 'successor', '');
                """)
        command.upgrade(config, "head")
        with TestClient(app) as client:
            before = export(client)
            successor = next(deck for deck in before["decks"] if deck["id"] == 1)
            assert erase(client, "decks", successor).status_code == 204
            after = export(client)
            assert [card["front"] for card in after["cards"]] == [
                "reused deck",
                "orphan",
                "Missing legacy card",
            ]
            assert after["reviews"] == before["reviews"]
            assert [review["card_id"] for review in after["reviews"]] == [1, 3]
            assert {card["deck_id"] for card in after["cards"]} <= {
                deck["id"] for deck in after["decks"]
            }
    finally:
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()
