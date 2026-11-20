from datetime import UTC, datetime, timedelta

import pytest

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
