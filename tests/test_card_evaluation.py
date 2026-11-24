from datetime import UTC, datetime

import pytest

from app.evaluation import EVALUATION_FIXTURES, evaluate_generated_card
from app.generator import GeneratedCard, MockGenerator, get_generator
from app.main import app


def create_deck(client):
    resp = client.post("/decks", json={"name": "Evaluation Deck"})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_reviewed_fixtures_match_expected_verdicts():
    assert {f.category for f in EVALUATION_FIXTURES} == {"vacancy", "aws_docs", "interview"}
    for fixture in EVALUATION_FIXTURES:
        for case in fixture.cases:
            ev = evaluate_generated_card(
                front=case.front,
                back=case.back,
                kind=case.kind,
                source_text=fixture.source_text,
                accepted_answers=case.accepted_answers,
                explanation=case.explanation,
            )
            assert (ev.status, ev.ready_for_review) == (
                case.expected_status,
                case.expected_status == "draft",
            ), case.id
            checks = ev.checks.model_dump()
            assert tuple(k for k, v in checks.items() if v == "fail") == case.expected_failed_checks
            assert tuple(k for k, v in checks.items() if v == "warn") == case.expected_warn_checks
            assert ev.uncertainty
            assert bool(ev.rejection_reasons) is (ev.status == "rejected")


def test_mock_generator_observations_and_fallback():
    gen = MockGenerator()
    vacancy, aws_doc = EVALUATION_FIXTURES[0], EVALUATION_FIXTURES[1]
    v_evals = [
        (
            c.kind,
            evaluate_generated_card(
                front=c.front, back=c.back, kind=c.kind, source_text=vacancy.source_text
            ),
        )
        for c in gen.generate(vacancy.source_text, 8)
    ]
    assert len(v_evals) == 8 and all(ev.status == "draft" for _, ev in v_evals)
    scaffold = next(ev for kind, ev in v_evals if kind == "interview_phrase")
    assert scaffold.checks.ambiguity == "warn" and any("[task]" in u for u in scaffold.uncertainty)
    assert len(gen.generate(aws_doc.source_text, 6)) == 3

    no_glossary = "Amazon VPC security groups and IAM roles protect subnet workloads."
    fallback = gen.generate(no_glossary, 6)
    assert len(fallback) == 2
    for c in fallback:
        ev = evaluate_generated_card(
            front=c.front, back=c.back, kind=c.kind, source_text=no_glossary
        )
        assert ev.status == "rejected" and ev.checks.source_grounding == "fail"


def test_evaluator_edge_cases():
    src = (
        "Amazon VPC security groups are stateful firewalls; network ACLs are stateless. "
        "PostgreSQL is relational."
    )
    ok = evaluate_generated_card(
        front="How do VPC security groups differ from network ACLs?",
        back="Security groups are stateful firewalls, whereas network ACLs are stateless filters.",
        kind="sentence",
        source_text=src,
    )
    assert ok.status == "draft" and ok.checks.technical_accuracy == "pass"

    for front, back, kind, failed_check in (
        (
            "How do NACLs work?",
            "Network ACLs are stateful subnet filters.",
            "sentence",
            "technical_accuracy",
        ),
        (
            "What is PostgreSQL?",
            "PostgreSQL is a NoSQL document database.",
            "vocabulary",
            "technical_accuracy",
        ),
        ("Explain VPC firewalls.", "TODO finish this VPC explanation.", "vocabulary", "ambiguity"),
        (
            "What is an Amazon VPC security group?",
            "Helm charts package Kubernetes YAML templates and default values.",
            "vocabulary",
            "source_grounding",
        ),
    ):
        ev = evaluate_generated_card(front=front, back=back, kind=kind, source_text=src)
        assert ev.status == "rejected" and ev.checks.model_dump()[failed_check] == "fail"

    lab = "In my lab project, I configured a VPC security group for HTTPS access."
    assert (
        evaluate_generated_card(
            front="How did you configure HTTPS access in your VPC lab?",
            back=lab,
            kind="interview_phrase",
            source_text=lab,
        ).status
        == "draft"
    )


def test_preview_returns_drafts_without_persisting_and_flags_bad_generator(client):
    did = create_deck(client)
    vacancy, aws_doc = EVALUATION_FIXTURES[0], EVALUATION_FIXTURES[1]
    resp = client.post(
        "/cards/generate/preview",
        json={
            "deck_id": did,
            "text": vacancy.source_text,
            "max_cards": 8,
            "source_label": " AWS JD ",
        },
    )
    assert resp.status_code == 200
    drafts = resp.json()
    assert len(drafts) == 8
    assert all(
        d["source_label"] == "AWS JD" and d["evaluation"]["status"] == "draft" for d in drafts
    )
    assert all(d["evaluation"]["uncertainty"] for d in drafts)
    assert client.get("/cards", params={"deck_id": did}).json() == []
    assert client.get(f"/decks/{did}/due").json() == []
    assert (
        client.post(
            "/cards/generate/preview", json={"deck_id": 999, "text": vacancy.source_text}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/cards/generate/preview", json={"deck_id": did, "text": "AWS Python\x00role"}
        ).status_code
        == 422
    )

    class BadGenerator:
        def generate(self, text, max_cards):
            return [
                GeneratedCard(
                    "Explain Helm charts.", "Helm charts package Kubernetes YAML.", "vocabulary"
                ),
                GeneratedCard(
                    "How do security groups work?",
                    "Security groups are stateless firewalls.",
                    "sentence",
                ),
            ]

    app.dependency_overrides[get_generator] = BadGenerator
    bad = client.post(
        "/cards/generate/preview", json={"deck_id": did, "text": aws_doc.source_text}
    ).json()
    assert [d["evaluation"]["status"] for d in bad] == ["rejected", "rejected"]
    assert bad[0]["evaluation"]["checks"]["source_grounding"] == "fail"
    assert bad[1]["evaluation"]["checks"]["technical_accuracy"] == "fail"
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_approve_persists_supported_draft_and_handles_missing_deck(client, set_clock):
    set_clock(datetime(2026, 5, 10, 15, 0, 0, tzinfo=UTC))
    did = create_deck(client)
    aws_doc = EVALUATION_FIXTURES[1]
    payload = {
        "deck_id": did,
        "front": "An Amazon VPC ____ acts as a stateful virtual firewall.",
        "back": "security group",
        "kind": "cloze",
        "source_label": "AWS VPC Docs",
        "accepted_answers": ["VPC security group"],
        "explanation": "Return traffic is automatically allowed.",
        "source_text": aws_doc.source_text,
    }
    approved = client.post("/cards/generate/approve", json=payload)
    assert approved.status_code == 201
    body = approved.json()
    assert body["evaluation"]["ready_for_review"] is True
    assert body["card"]["due_date"] == "2026-05-10"
    assert body["card"]["accepted_answers"] == ["VPC security group"]
    assert [c["id"] for c in client.get(f"/decks/{did}/due").json()] == [body["card"]["id"]]
    assert (
        client.post("/cards/generate/approve", json={**payload, "deck_id": 999}).status_code == 404
    )


@pytest.mark.parametrize(
    "case",
    [c for f in EVALUATION_FIXTURES for c in f.cases if c.expected_status == "rejected"],
    ids=lambda c: c.id,
)
def test_approve_rejects_unsupported_cases_without_persisting(client, case):
    did = create_deck(client)
    source_text = next(f.source_text for f in EVALUATION_FIXTURES if case in f.cases)
    resp = client.post(
        "/cards/generate/approve",
        json={
            "deck_id": did,
            "front": case.front,
            "back": case.back,
            "kind": case.kind,
            "accepted_answers": list(case.accepted_answers),
            "explanation": case.explanation,
            "source_text": source_text,
        },
    )
    assert resp.status_code == 422
    assert client.get("/cards", params={"deck_id": did}).json() == []
    assert client.get(f"/decks/{did}/due").json() == []
