from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import insert, text

from app.generator import GeneratedCard, get_generator
from app.main import app
from app.models import Deck

VACANCY = "Cloud Support Engineer vacancy: troubleshoot AWS, Linux and PostgreSQL incidents."
AWS_DOCS = "AWS security groups are stateful. Network ACLs are stateless. Route tables use IP."
INTERVIEW = "I saved $50,000. I migrated 10 AWS services and 5 GCP services to AWS."
PROMPT = "What does the source say?"
PRACTICE_FRONT = "How would you discuss your experience with AWS?"
PRACTICE = (
    "Practice: I have worked with AWS to [task]. "
    "Use a truthful example and explain your contribution."
)

CASES = [
    pytest.param(
        "The sample deck contains 2 cards.",
        "cards",
        "cloze",
        {"front": "The sample deck contains 2 ____."},
        201,
        None,
        id="grounded-numeric-cloze",
    ),
    pytest.param(
        "AWS security groups are stateful.",
        "AWS security groups are stateful.",
        "sentence",
        {"front": "AWS security groups are stateful?"},
        422,
        "ambiguity",
        id="repeated-prompt",
    ),
    pytest.param(
        "AWS security groups are stateful. Network ACLs are stateless.",
        "Network ACLs are stateless.",
        "sentence",
        {"front": "Which AWS control is stateful?"},
        422,
        "ambiguity",
        id="grounded-answer-wrong-control",
    ),
    pytest.param(
        "AWS security groups are stateful. AWS network ACLs are stateless.",
        "AWS network ACLs are stateless.",
        "sentence",
        {"front": "Which AWS control is stateful?"},
        422,
        "ambiguity",
        id="grounded-answer-wrong-property-shared-topic",
    ),
    pytest.param(
        "AWS documentation mentions stateful filtering. AWS security groups are stateful.",
        "AWS documentation mentions stateful filtering.",
        "sentence",
        {"front": "Which AWS control is stateful?"},
        422,
        "ambiguity",
        id="grounded-answer-mentions-property-without-identifying-control",
    ),
    pytest.param(
        "AWS network ACLs are not stateful. AWS security groups are stateful.",
        "AWS network ACLs are not stateful.",
        "sentence",
        {"front": "Which AWS control is stateful?"},
        422,
        "ambiguity",
        id="grounded-answer-negates-requested-property",
    ),
    pytest.param(
        AWS_DOCS,
        "AWS security groups are stateful.",
        "sentence",
        {
            "front": "Which AWS control is stateful?",
            "accepted_answers": ["Network ACLs are stateless."],
        },
        422,
        "ambiguity",
        id="grounded-alternative-wrong-control",
    ),
    pytest.param(
        AWS_DOCS,
        "AWS security groups are stateful.",
        "sentence",
        {"front": "Which AWS control is stateful?"},
        201,
        None,
        id="grounded-answer-right-control",
    ),
    pytest.param(
        "The API uses PostgreSQL. The API uses Redis.",
        "The API uses Redis.",
        "sentence",
        {"front": "Which database does the API use for PostgreSQL queries?"},
        422,
        "ambiguity",
        id="grounded-answer-wrong-technology-shared-topic",
    ),
    pytest.param(
        AWS_DOCS,
        "Network ACLs are stateless.",
        "sentence",
        {"front": "What benefit does Python provide?"},
        422,
        "ambiguity",
        id="grounded-answer-unrelated-topic",
    ),
    pytest.param(
        "I saved the cloud configuration. I saved $50,000.",
        "I saved the cloud configuration.",
        "behavioral",
        {"front": "How much did you save?"},
        422,
        "ambiguity",
        id="grounded-answer-missing-amount",
    ),
    pytest.param(
        "I saved the cloud configuration. I deployed 10 servers.",
        "I saved the cloud configuration. I deployed 10 servers.",
        "behavioral",
        {"front": "How much did you save?"},
        422,
        "ambiguity",
        id="grounded-answer-amount-in-another-sentence",
    ),
    pytest.param(
        INTERVIEW,
        "I saved $50,000.",
        "behavioral",
        {"front": "How much did you save?"},
        201,
        None,
        id="grounded-answer-right-amount",
    ),
    pytest.param(
        AWS_DOCS,
        "AWS security groups are stateful.",
        "sentence",
        {"front": "Why are AWS security groups stateful?"},
        422,
        "ambiguity",
        id="grounded-answer-repeats-claim-without-explanation",
    ),
    pytest.param(
        "AWS security groups are stateful because they track connections.",
        "AWS security groups are stateful because they track connections.",
        "sentence",
        {"front": "Why are AWS security groups stateful?"},
        201,
        None,
        id="grounded-answer-explains-claim",
    ),
    pytest.param(
        VACANCY,
        "A relational database supporting SQL and transactions.",
        "vocabulary",
        {"front": "Explain 'postgresql' in technical English."},
        201,
        None,
        id="grounded-answer-glossary-definition",
    ),
    pytest.param(INTERVIEW, "I saved $50,000.", "behavioral", {}, 201, None, id="exact-quote"),
    pytest.param(
        "I saved $50,000?",
        "I saved $50,000.",
        "behavioral",
        {},
        422,
        "technical_accuracy",
        id="question-is-not-evidence",
    ),
    pytest.param(INTERVIEW, INTERVIEW, "behavioral", {}, 201, None, id="full-interview-quote"),
    pytest.param(
        INTERVIEW,
        "I migrated 5 AWS services.",
        "behavioral",
        {},
        422,
        "technical_accuracy",
        id="count-destination",
    ),
    pytest.param(
        "I worked with AWS, then my colleague led production migrations.",
        "I worked with AWS, then led production migrations.",
        "behavioral",
        {},
        422,
        "technical_accuracy",
        id="then-led",
    ),
    pytest.param(
        "I led the PostgreSQL migration. My colleague led the Docker migration.",
        "I led the Docker migration.",
        "behavioral",
        {},
        422,
        "technical_accuracy",
        id="cross-sentence",
    ),
    pytest.param(
        "PostgreSQL tuning improved throughput by 1,170%.",
        "PostgreSQL tuning improved throughput by 2,170%.",
        "sentence",
        {},
        422,
        "technical_accuracy",
        id="comma-suffix",
    ),
    pytest.param(
        "PostgreSQL tuning improved throughput by 170%.",
        "PostgreSQL tuning improved throughput by 70%.",
        "sentence",
        {},
        422,
        "technical_accuracy",
        id="percent-suffix",
    ),
    pytest.param(
        "I reduced AWS latency from 200ms to 100ms.",
        "I reduced AWS latency from 100ms to 200ms.",
        "behavioral",
        {},
        422,
        "technical_accuracy",
        id="metric-direction",
    ),
    pytest.param(
        "I reduced AWS latency from 200ms to 100ms and database latency from 300ms to 200ms.",
        "I reduced AWS latency to 200ms.",
        "behavioral",
        {},
        422,
        "technical_accuracy",
        id="other-metric-target",
    ),
    pytest.param(
        "I migrated our API from PostgreSQL to Docker.",
        "I migrated our API from Docker to PostgreSQL.",
        "behavioral",
        {},
        422,
        "technical_accuracy",
        id="technology-direction",
    ),
    pytest.param(
        VACANCY,
        "Practice: I have worked with AWS to lead the production migration.",
        "interview_phrase",
        {"front": PRACTICE_FRONT},
        422,
        "technical_accuracy",
        id="practice-claim",
    ),
    pytest.param(
        VACANCY + " My colleague led production migrations.",
        "Practice: I have worked with AWS to [task], and led production migrations. "
        "Use a truthful example.",
        "interview_phrase",
        {"front": PRACTICE_FRONT},
        422,
        "technical_accuracy",
        id="practice-coordinated-claim",
    ),
    pytest.param(
        AWS_DOCS,
        PRACTICE,
        "interview_phrase",
        {"front": "Which AWS control is stateful?"},
        422,
        "ambiguity",
        id="irrelevant-interview-scaffold",
    ),
    pytest.param(
        AWS_DOCS,
        "Use STAR: describe the Situation, Task, Action and Result. "
        "Choose a real experience; do not invent an outcome.",
        "behavioral",
        {"front": "Which AWS control is stateful?"},
        422,
        "ambiguity",
        id="irrelevant-star-scaffold",
    ),
    pytest.param(
        VACANCY,
        PRACTICE,
        "interview_phrase",
        {"front": PRACTICE_FRONT},
        201,
        None,
        id="vacancy-practice",
    ),
    pytest.param(
        AWS_DOCS, "IP", "cloze", {"front": "Route tables use ____."}, 201, None, id="aws-docs-cloze"
    ),
    pytest.param(
        AWS_DOCS,
        "AWS security groups are stateful.",
        "sentence",
        {"accepted_answers": ["AWS security groups are stateless."]},
        422,
        "technical_accuracy",
        id="contradictory-alternative",
    ),
]
for field in ("explanation", "accepted_answers"):
    value = "I led the PostgreSQL migration [project]."
    CASES.append(
        pytest.param(
            "I led the PostgreSQL migration.",
            "I led the PostgreSQL migration.",
            "sentence",
            {field: [value] if field == "accepted_answers" else value},
            422,
            "ambiguity",
            id=field,
        )
    )


def test_sql_imports_get_new_deck_identity(db_engine):
    with db_engine.begin() as conn:
        rows = (
            conn.execute(
                text(
                    "INSERT INTO decks (name, description) "
                    "VALUES ('Imported', ''), ('Imported', '') RETURNING incarnation"
                )
            )
            .scalars()
            .all()
        )
    assert len(set(rows)) == 2
    assert all(len(value) == 32 for value in rows)


@pytest.fixture
def deck(client):
    response = client.post("/decks", json={"name": "Evaluation"})
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.parametrize("source_text, back, kind, edits, status, check", CASES)
def test_evaluator(source_text, back, kind, edits, status, check):
    from app.evaluation import evaluate_generated_card

    result = evaluate_generated_card(
        source_text=source_text, **({"front": PROMPT, "back": back, "kind": kind} | edits)
    )
    assert result.ready_for_review is (status == 201)
    if check:
        assert getattr(result.checks, check) == "fail"


@pytest.mark.parametrize("source_text, back, kind, edits, status, check", CASES)
def test_approval(client, deck, source_text, back, kind, edits, status, check):
    payload = dict(deck_id=deck, front=PROMPT, back=back, kind=kind, source_text=source_text)
    response = client.post("/cards/generate/approve", json=payload | edits)
    assert response.status_code == status, response.text
    cards = client.get(f"/decks/{deck}/due").json()
    if status == 201:
        assert response.json()["evaluation"]["ready_for_review"]
        assert cards == [response.json()["card"]]
    else:
        assert check in response.json()["detail"]["checks"]
        assert not cards


def test_preview_then_edit_and_approve(client, db_engine, deck):
    response = client.post(
        "/cards/generate/preview",
        json={
            "deck_id": deck,
            "text": VACANCY,
            "max_cards": 6,
            "source_label": "vacancy",
        },
    )
    assert response.status_code == 200
    assert client.get(f"/decks/{deck}/due").json() == []
    draft = next(card for card in response.json() if card["kind"] == "interview_phrase")
    assert draft["evaluation"]["uncertainty"]
    assert draft["evaluation"]["checks"]["ambiguity"] == "warn"
    edited = draft | {
        "source_text": VACANCY,
        "front": "Which AWS incidents does the vacancy mention?",
        "back": VACANCY,
    }
    approved = client.post("/cards/generate/approve", json=edited)
    assert approved.status_code == 201
    assert client.get(f"/decks/{deck}/due").json()[0]["back"] == VACANCY

    assert client.delete(f"/decks/{deck}").status_code == 204
    if db_engine.dialect.name == "sqlite":
        assert client.post("/decks", json={"name": "Evaluation"}).json()["id"] == deck
    else:
        with db_engine.begin() as conn:
            conn.execute(insert(Deck).values(id=deck, name="Evaluation"))
    assert client.post("/cards/generate/approve", json=edited).status_code == 404
    assert client.get(f"/decks/{deck}/due").json() == []


@pytest.mark.parametrize(
    "route", ["/cards/generate", "/cards/generate/preview", "/cards/generate/approve"]
)
def test_pending_request_cannot_target_recreated_deck(client, db_engine, deck, monkeypatch, route):
    entered, resume = Event(), Event()

    def pause():
        entered.set()
        assert resume.wait(10)

    class PendingGenerator:
        def generate(self, text, max_cards):
            pause()
            return [GeneratedCard(PROMPT, INTERVIEW, "behavioral")]

    app.dependency_overrides[get_generator] = PendingGenerator
    if route.endswith("/approve"):
        from app import main

        evaluate = main.evaluate_generated_card

        def pending_evaluation(**kwargs):
            pause()
            return evaluate(**kwargs)

        monkeypatch.setattr(main, "evaluate_generated_card", pending_evaluation)

    with ThreadPoolExecutor() as executor:
        request = executor.submit(
            client.post,
            route,
            json={
                "deck_id": deck,
                "text": INTERVIEW,
                "source_text": INTERVIEW,
                "front": PROMPT,
                "back": INTERVIEW,
                "kind": "behavioral",
            },
        )
        try:
            assert entered.wait(10), request.result(timeout=1).text
            assert client.delete(f"/decks/{deck}").status_code == 204
            if db_engine.dialect.name == "sqlite":
                assert client.post("/decks", json={"name": "Evaluation"}).json()["id"] == deck
            else:
                with db_engine.begin() as conn:
                    conn.execute(insert(Deck).values(id=deck, name="Evaluation"))
        finally:
            resume.set()
        assert request.result(timeout=10).status_code == 404
    assert client.get(f"/decks/{deck}").json()["name"] == "Evaluation"
    assert client.get(f"/decks/{deck}/due").json() == []
