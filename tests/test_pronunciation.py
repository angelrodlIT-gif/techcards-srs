import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Semaphore

import pytest
from sqlalchemy import create_engine, event
from starlette.requests import Request

from app.models import Base

HEADERS = {"Recording-Consent": "true", "Content-Type": "audio/webm"}


@pytest.fixture
def db_engine(tmp_path):
    url = os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    engine = create_engine(url, pool_size=1, max_overflow=0, pool_timeout=2)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture(autouse=True)
def direct_host(client):
    client.headers["Host"] = "localhost"


@pytest.mark.parametrize("change", ["edit", "recreate", "none"])
def test_upload_revalidates_after_streaming(client, db_engine, monkeypatch, change):
    if change == "recreate" and db_engine.dialect.name != "sqlite":
        pytest.skip("Tests SQLite row ID reuse")
    deck = client.post("/decks", json={"name": "Practice"}).json()
    payload = {"deck_id": deck["id"], "front": "Repeat", "back": "Deploy the service"}
    card = client.post("/cards", json=payload).json()
    recording = f"/study/{card['id']}/pronunciation/recording"
    card_url = f"/cards/{card['id']}"
    paused, resume = Semaphore(0), Event()
    connections = set()

    def checkout(_, record, __):
        connections.add(record)

    def checkin(_, record):
        connections.remove(record)

    event.listen(db_engine, "checkout", checkout)
    event.listen(db_engine, "checkin", checkin)
    original = Request.stream

    async def stream(request):
        if request.headers.get("x-test-pause"):
            paused.release()
            assert await asyncio.to_thread(resume.wait, 5)
        async for chunk in original(request):
            yield chunk

    monkeypatch.setattr(Request, "stream", stream)
    with ThreadPoolExecutor(max_workers=4) as jobs:
        old = jobs.submit(
            client.post, recording, content=b"old", headers={**HEADERS, "X-Test-Pause": "1"}
        )
        try:
            assert paused.acquire(timeout=5), old.result() if old.done() else None
            if change == "none":
                peers = [
                    jobs.submit(
                        client.post,
                        recording,
                        content=b"old",
                        headers={**HEADERS, "X-Test-Pause": "1"},
                    )
                    for _ in range(2)
                ]
                for _ in peers:
                    assert paused.acquire(timeout=5)
                assert not connections
                assert jobs.submit(client.get, card_url).result(timeout=2).status_code == 200
            else:
                if change == "edit":
                    assert (
                        client.put(card_url, json={**payload, "back": "New reference"}).status_code
                        == 200
                    )
                else:
                    assert client.delete(card_url).status_code == 204
                    assert client.post("/cards", json=payload).json()["id"] == card["id"]
                assert client.post(recording, content=b"new", headers=HEADERS).status_code == 201
        finally:
            resume.set()
        if change == "none":
            assert all(peer.result(timeout=5).status_code == 201 for peer in peers)
        assert old.result(timeout=5).status_code == (201 if change == "none" else 409)
    assert client.get(recording).content == (b"old" if change == "none" else b"new")


def test_recording_controls_and_transcript_fallback(client):
    deck = client.post("/decks", json={"name": "Practice"}).json()
    card = client.post(
        "/cards",
        json={"deck_id": deck["id"], "front": "Repeat", "back": "Deploy the service"},
    ).json()
    base = f"/study/{card['id']}/pronunciation"
    recording = f"{base}/recording"
    assert client.post(recording, content=b"audio").status_code == 422
    assert (
        client.post(
            recording, content=b"audio", headers={**HEADERS, "X-Forwarded-For": "127.0.0.1"}
        ).status_code
        == 403
    )
    assert (
        client.post(recording, content=b"x" * (512 * 1024 + 1), headers=HEADERS).status_code == 413
    )
    assert client.post(recording, content=b"clip", headers=HEADERS).status_code == 201
    replay = client.get(recording)
    assert replay.content == b"clip"
    assert replay.headers["cache-control"] == "no-store"
    assert client.delete(recording).status_code == 204
    assert client.get(recording).status_code == 404
    result = client.post(
        f"{base}/compare", json={"microphone_available": False, "spoken_transcript": "Deploy"}
    ).json()
    assert result["recording_status"] == "microphone_denied_fallback"
    assert result["matched_terms"] == ["deploy"]
    assert result["missing_terms"] == ["the", "service"]


def test_edit_preserves_upload_completed_after_reference_commit(client, monkeypatch):
    import app.main as api

    deck = client.post("/decks", json={"name": "Practice"}).json()
    payload = {"deck_id": deck["id"], "front": "Repeat", "back": "First reference"}
    card = client.post("/cards", json=payload).json()
    card_url = f"/cards/{card['id']}"
    recording = f"/study/{card['id']}/pronunciation/recording"
    assert client.post(recording, content=b"previous", headers=HEADERS).status_code == 201
    committed, uploaded = Event(), Event()
    original = api.save

    def pause_after_commit(db, obj):
        saved = original(db, obj)
        db.commit()
        committed.set()
        assert uploaded.wait(5)
        return saved

    monkeypatch.setattr(api, "save", pause_after_commit)
    with ThreadPoolExecutor(max_workers=1) as jobs:
        edit = jobs.submit(client.put, card_url, json={**payload, "back": "New reference"})
        try:
            assert committed.wait(5)
            assert client.post(recording, content=b"valid", headers=HEADERS).status_code == 201
        finally:
            uploaded.set()
        assert edit.result(timeout=5).status_code == 200
    assert client.get(recording).content == b"valid"
