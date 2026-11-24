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
        "explanation": "Stateful security groups allow return traffic automatically.",
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


def test_ungrounded_percentage_metric_rejected_unit_and_approve(client):
    src = "I reduced PostgreSQL query latency."
    front = "How did you improve PostgreSQL performance?"
    back = "I reduced PostgreSQL query latency by 70%."

    ev = evaluate_generated_card(front=front, back=back, kind="interview_phrase", source_text=src)
    assert ev.status == "rejected"
    assert ev.ready_for_review is False
    assert ev.checks.technical_accuracy == "fail"

    did = create_deck(client)
    resp = client.post(
        "/cards/generate/approve",
        json={
            "deck_id": did,
            "front": front,
            "back": back,
            "kind": "interview_phrase",
            "source_text": src,
        },
    )
    assert resp.status_code == 422
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_accepted_answers_and_explanation_are_evaluated_unit_and_approve(client):
    src = "Amazon VPC security groups are stateful firewalls for EC2 instances."
    front = "How do AWS VPC security groups work?"
    back = "Security groups are stateful firewalls."

    contradiction = evaluate_generated_card(
        front=front,
        back=back,
        kind="sentence",
        source_text=src,
        accepted_answers=["Security groups are stateless firewalls."],
    )
    assert contradiction.status == "rejected"
    assert contradiction.checks.technical_accuracy == "fail"

    ungrounded_alt = evaluate_generated_card(
        front=front,
        back=back,
        kind="sentence",
        source_text=src,
        accepted_answers=["Helm charts package Kubernetes templates."],
    )
    assert ungrounded_alt.status == "rejected"
    assert ungrounded_alt.checks.source_grounding == "fail"

    invalid_alt = evaluate_generated_card(
        front=front,
        back=back,
        kind="sentence",
        source_text=src,
        accepted_answers=["12345 !!!"],
    )
    assert invalid_alt.status == "rejected"
    assert invalid_alt.checks.english_usefulness == "fail"

    unresolved_expl = evaluate_generated_card(
        front=front,
        back=back,
        kind="sentence",
        source_text=src,
        explanation="TODO verify return traffic behavior.",
    )
    assert unresolved_expl.status == "rejected"
    assert unresolved_expl.checks.ambiguity == "fail"

    did = create_deck(client)
    for extra in (
        {"accepted_answers": ["Security groups are stateless firewalls."]},
        {"accepted_answers": ["Helm charts package Kubernetes templates."]},
        {"explanation": "TODO verify return traffic behavior."},
    ):
        resp = client.post(
            "/cards/generate/approve",
            json={
                "deck_id": did,
                "front": front,
                "back": back,
                "kind": "sentence",
                "source_text": src,
                **extra,
            },
        )
        assert resp.status_code == 422
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_single_word_cloze_completion_is_accepted_unit_and_approve(client):
    src = "PostgreSQL supports transactions."
    front = "PostgreSQL supports ____."
    back = "transactions"

    ev = evaluate_generated_card(front=front, back=back, kind="cloze", source_text=src)
    assert ev.status == "draft"
    assert ev.ready_for_review is True
    assert ev.checks.english_usefulness == "pass"
    assert ev.checks.source_grounding == "pass"

    did = create_deck(client)
    resp = client.post(
        "/cards/generate/approve",
        json={
            "deck_id": did,
            "front": front,
            "back": back,
            "kind": "cloze",
            "source_text": src,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["evaluation"]["ready_for_review"] is True
    assert body["card"]["back"] == "transactions"
    assert len(client.get("/cards", params={"deck_id": did}).json()) == 1


def test_substring_metric_match_rejected_unit_and_approve(client):
    src = "I increased PostgreSQL throughput by 170%."
    front = "How did you improve PostgreSQL throughput?"
    back = "I increased PostgreSQL throughput by 70%."

    ev = evaluate_generated_card(front=front, back=back, kind="interview_phrase", source_text=src)
    assert ev.status == "rejected"
    assert ev.ready_for_review is False
    assert ev.checks.technical_accuracy == "fail"

    did = create_deck(client)
    resp = client.post(
        "/cards/generate/approve",
        json={
            "deck_id": did,
            "front": front,
            "back": back,
            "kind": "interview_phrase",
            "source_text": src,
        },
    )
    assert resp.status_code == 422
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_unsupported_first_person_claim_with_different_pronoun_rejected(client):
    src = "Our team uses PostgreSQL."
    front = "What database does your team use?"
    valid_back = "Our team uses PostgreSQL in production."
    claim = "I led the PostgreSQL migration."

    ev_alt = evaluate_generated_card(
        front=front,
        back=valid_back,
        kind="interview_phrase",
        source_text=src,
        accepted_answers=[claim],
    )
    assert ev_alt.status == "rejected"
    assert ev_alt.checks.technical_accuracy == "fail"

    ev_back = evaluate_generated_card(
        front=front,
        back=claim,
        kind="interview_phrase",
        source_text=src,
    )
    assert ev_back.status == "rejected"
    assert ev_back.checks.technical_accuracy == "fail"

    did = create_deck(client)
    for payload in (
        {"back": valid_back, "accepted_answers": [claim]},
        {"back": claim},
    ):
        resp = client.post(
            "/cards/generate/approve",
            json={
                "deck_id": did,
                "front": front,
                "kind": "interview_phrase",
                "source_text": src,
                **payload,
            },
        )
        assert resp.status_code == 422
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_explanation_usefulness_ambiguity_and_grounding_rejected(client):
    src = "Amazon VPC security groups are stateful firewalls for EC2 instances."
    front = "How do AWS VPC security groups work?"
    back = "Security groups are stateful firewalls."

    cases = (
        ("12345 !!!", "english_usefulness"),
        (front, "ambiguity"),
        ("Helm charts package Kubernetes templates.", "source_grounding"),
    )
    did = create_deck(client)
    for explanation, failed_check in cases:
        ev = evaluate_generated_card(
            front=front,
            back=back,
            kind="sentence",
            source_text=src,
            explanation=explanation,
        )
        assert ev.status == "rejected"
        assert ev.checks.model_dump()[failed_check] == "fail"

        resp = client.post(
            "/cards/generate/approve",
            json={
                "deck_id": did,
                "front": front,
                "back": back,
                "kind": "sentence",
                "source_text": src,
                "explanation": explanation,
            },
        )
        assert resp.status_code == 422
    assert client.get("/cards", params={"deck_id": did}).json() == []


def test_two_char_technical_token_cloze_accepted_unit_and_approve(client):
    src = "IP addresses identify hosts."
    front = "____ addresses identify hosts."
    back = "IP"

    ev = evaluate_generated_card(front=front, back=back, kind="cloze", source_text=src)
    assert ev.status == "draft"
    assert ev.ready_for_review is True
    assert ev.checks.english_usefulness == "pass"
    assert ev.checks.source_grounding == "pass"

    did = create_deck(client)
    resp = client.post(
        "/cards/generate/approve",
        json={
            "deck_id": did,
            "front": front,
            "back": back,
            "kind": "cloze",
            "source_text": src,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["evaluation"]["ready_for_review"] is True
    assert body["card"]["back"] == "IP"
    assert len(client.get("/cards", params={"deck_id": did}).json()) == 1
