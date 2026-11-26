from datetime import UTC, datetime

from app.learning import summarize_learning

SUMMARY = "/analytics/learning"


def test_empty_learning_summary(client):
    response = client.get(SUMMARY)
    assert response.status_code == 200
    summary = response.json()
    assert summary["semantics_version"] == 1
    assert summary["date_timezone"] == "America/Cancun"
    assert summary["reviews"] == {
        "recall": {"numerator": 0, "denominator": 0},
        "lapse": {"numerator": 0, "denominator": 0},
    }
    assert summary["practice"]["sessions"] == 0
    assert summary["practice"]["observed_span_seconds"] is None
    assert summary["practice"]["active_study_seconds"] is None
    assert summary["practice"]["response_seconds"] is None
    assert (
        client.get(SUMMARY, params={"start": "2026-11-25", "end": "2026-11-24"}).status_code == 422
    )
    assert client.get(SUMMARY, params={"start": "not-a-date"}).status_code == 422


def test_learning_summary_reads_real_review_and_error_routes(client, set_clock):
    set_clock(datetime(2026, 11, 24, 4, 45, tzinfo=UTC))
    deck_id = client.post("/decks", json={"name": "Practice"}).json()["id"]
    draft = {"attempted": "a subnet", "corrected": "an isolated subnet", "rationale": "Precision"}
    error_ids = [client.post("/errors", json=draft).json()["id"] for _ in range(4)]

    approved = client.post(f"/errors/{error_ids[0]}/approve", json={"deck_id": deck_id})
    card_id = approved.json()["card"]["id"]
    deleted = client.post(f"/errors/{error_ids[1]}/approve", json={"deck_id": deck_id})
    assert client.delete(f"/cards/{deleted.json()['card']['id']}").status_code == 204
    assert client.post(f"/errors/{error_ids[2]}/discard").status_code == 200

    assert client.get("/study/next", params={"deck_id": deck_id}).status_code == 200
    assert client.post(f"/study/{card_id}/reveal").status_code == 200
    assert client.get(SUMMARY).json()["practice"]["sessions"] == 0

    assert client.post(f"/study/{card_id}/grade", json={"quality": 3}).status_code == 201
    set_clock(datetime(2026, 11, 24, 5, 15, tzinfo=UTC))
    failed = {"card_id": card_id, "quality": 2}
    first = client.post("/reviews", json=failed)
    repeat = client.post("/reviews", json=failed)
    assert first.status_code == repeat.status_code == 201
    assert first.json()["id"] != repeat.json()["id"]
    set_clock(datetime(2026, 11, 24, 5, 45, 1, tzinfo=UTC))
    assert client.post(f"/study/{card_id}/grade", json={"quality": 5}).status_code == 201

    all_time = client.get(SUMMARY).json()
    assert all_time["reviews"] == {
        "recall": {"numerator": 2, "denominator": 4},
        "lapse": {"numerator": 1, "denominator": 1},
    }
    assert all_time["practice"] == {
        "sessions": 2,
        "first_review_at": "2026-11-24T04:45:00Z",
        "last_review_at": "2026-11-24T05:45:01Z",
        "first_review_cancun_date": "2026-11-23",
        "last_review_cancun_date": "2026-11-24",
        "observed_span_seconds": 1800.0,
        "active_study_seconds": None,
        "response_seconds": None,
    }
    assert all_time["data_quality"]["possible_duplicate_reviews"] == 1
    assert all_time["error_correction"] == {
        "current_drafts": 1,
        "current_discarded": 1,
        "current_approved": 2,
        "current_approved_without_card": 1,
        "first_review_recall": {"numerator": 1, "denominator": 1},
    }

    window = client.get(SUMMARY, params={"start": "2026-11-24", "end": "2026-11-24"}).json()
    assert window["reviews"]["recall"] == {"numerator": 1, "denominator": 3}
    assert window["reviews"]["lapse"] == {"numerator": 1, "denominator": 1}
    assert window["practice"]["observed_span_seconds"] == 0.0
    assert window["error_correction"]["first_review_recall"] == {"numerator": 0, "denominator": 0}
    assert window["error_correction"]["current_approved"] == 2
    prior = client.get(SUMMARY, params={"end": "2026-11-23"}).json()
    assert prior["reviews"]["recall"] == {"numerator": 1, "denominator": 1}
    assert prior["practice"]["observed_span_seconds"] == 0.0
    assert prior["error_correction"]["first_review_recall"] == {"numerator": 1, "denominator": 1}
    assert client.get(SUMMARY).json() == all_time


def test_unknown_review_data_does_not_fill_missing_outcomes():
    class LegacyRows:
        def execute(self, _):
            def at(minute):
                return datetime(2026, 11, 24, 12, minute, tzinfo=UTC)

            return [
                (1, 1, 5, at(0), None),
                (2, 1, 1, at(1), None),
                (3, 1, 1, None, None),
                (4, 2, 5, at(2), None),
                (5, 2, None, at(3), None),
                (6, 2, 1, at(4), None),
                (7, 3, 3.5, at(2), None),
                (8, 3, 4, at(4), None),
                (None, 1, None, None, "approved"),
                (None, 3, None, None, "approved"),
            ]

    summary = summarize_learning(LegacyRows(), None, None)
    assert summary.data_quality.reviews_without_timestamp == 1
    assert summary.data_quality.reviews_with_invalid_grade == 2
    assert summary.reviews.recall.model_dump() == {"numerator": 3, "denominator": 5}
    assert summary.reviews.lapse.denominator == 0
    assert summary.error_correction.first_review_recall.denominator == 0
