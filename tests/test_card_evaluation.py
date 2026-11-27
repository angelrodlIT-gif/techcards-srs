from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.evaluation import EVALUATION_FIXTURES, evaluate_generated_card
from app.generator import GeneratedCard, get_generator
from app.main import app
from app.models import Card, Deck


def create_deck(client, name: str = "Eval Deck") -> int:
    resp = client.post("/decks", json={"name": name, "description": "Evaluation tests"})
    assert resp.status_code == 201
    return resp.json()["id"]


# --- Reviewed fixtures (Issue #18) ---


def test_reviewed_fixtures_structure():
    assert [fixture.id for fixture in EVALUATION_FIXTURES] == [
        "vacancy-cloud-support",
        "aws-docs-vpc-iam",
        "interview-networking-star",
    ]
    total_cases = sum(len(fixture.cases) for fixture in EVALUATION_FIXTURES)
    assert total_cases == 12


@pytest.mark.parametrize(
    ("fixture", "case"),
    [(fixture, case) for fixture in EVALUATION_FIXTURES for case in fixture.cases],
    ids=lambda item: item.id if hasattr(item, "id") else item.name,
)
def test_reviewed_fixture_cases(fixture, case):
    result = evaluate_generated_card(
        front=case.front,
        back=case.back,
        kind=case.kind,
        source_text=fixture.source_text,
        accepted_answers=case.accepted_answers,
        explanation=case.explanation,
    )
    assert result.status == case.expected_status
    assert result.ready_for_review is (case.expected_status == "draft")
    assert result.checks.model_dump() == case.expected_checks
    if result.ready_for_review:
        assert result.rejection_reasons == []
        assert result.uncertainty
    else:
        assert result.rejection_reasons


# --- Issue #59 Finding 1: comma-separated & decimal metrics ---


@pytest.mark.parametrize(
    ("source_text", "card_back", "should_pass"),
    [
        (
            "PostgreSQL tuning cut tail latency by 1,170% during load testing.",
            "PostgreSQL tuning cut tail latency by 1,170% during load testing.",
            True,
        ),
        (
            "PostgreSQL tuning cut tail latency by 1,170% during load testing.",
            "PostgreSQL tuning cut tail latency by 170% during load testing.",
            False,
        ),
        (
            "PostgreSQL tuning cut tail latency by 1,170% during load testing.",
            "PostgreSQL tuning cut tail latency by 2,170% during load testing.",
            False,
        ),
        (
            "PostgreSQL tuning cut tail latency by 1.70% during load testing.",
            "PostgreSQL tuning cut tail latency by 1.70% during load testing.",
            True,
        ),
        (
            "PostgreSQL tuning cut tail latency by 1.70% during load testing.",
            "PostgreSQL tuning cut tail latency by 70% during load testing.",
            False,
        ),
        (
            "Cloud cost review saved $50,000. AWS rightsizing lowered idle compute.",
            "Cloud cost review saved $50,000 through AWS rightsizing.",
            True,
        ),
        (
            "Cloud cost review saved $50,000. AWS rightsizing lowered idle compute.",
            "Cloud cost review saved $ 50,000 through AWS rightsizing.",
            True,
        ),
        (
            "Cloud cost review saved $50,000. AWS rightsizing lowered idle compute.",
            "Cloud cost review saved $50 through AWS rightsizing.",
            False,
        ),
        (
            "Cloud cost review saved $50,000, reducing monthly AWS spend.",
            "Cloud cost review saved $50,000 on AWS spend.",
            True,
        ),
        (
            "Cloud cost review saved $50,000, reducing monthly AWS spend.",
            "Cloud cost review saved $50 on AWS spend.",
            False,
        ),
        (
            "Automated monitoring cut alert noise by 70%.",
            "Automated monitoring cut alert noise by 70 %.",
            True,
        ),
        (
            "Automated monitoring cut alert noise by 70%.",
            "Automated monitoring cut alert noise by 170%.",
            False,
        ),
        (
            "Automated monitoring cut alert noise by 170%.",
            "Automated monitoring cut alert noise by 70%.",
            False,
        ),
    ],
)
def test_metric_detection_commas_decimals_and_punctuation(source_text, card_back, should_pass):
    result = evaluate_generated_card(
        front="Summarize the documented performance impact.",
        back=card_back,
        kind="sentence",
        source_text=source_text,
    )
    if should_pass:
        assert result.checks.technical_accuracy == "pass"
        assert result.ready_for_review is True
    else:
        assert result.checks.technical_accuracy == "fail"
        assert result.ready_for_review is False
        assert "Card contains ungrounded metrics not present in source_text." in (
            result.rejection_reasons
        )


def test_ungrounded_metric_rejected_in_explanation_and_accepted_answers():
    source_text = "PostgreSQL tuning improved latency by 1,170% under peak load."
    exp_res = evaluate_generated_card(
        front="What improved PostgreSQL latency under peak load?",
        back="PostgreSQL tuning improved latency by 1,170%.",
        kind="sentence",
        explanation="This represents a 170% speedup on PostgreSQL.",
        source_text=source_text,
    )
    assert exp_res.checks.technical_accuracy == "fail"
    assert exp_res.ready_for_review is False

    ans_res = evaluate_generated_card(
        front="What improved PostgreSQL latency under peak load?",
        back="PostgreSQL tuning improved latency by 1,170%.",
        kind="sentence",
        accepted_answers=["PostgreSQL tuning improved latency by 2,170%."],
        source_text=source_text,
    )
    assert ans_res.checks.technical_accuracy == "fail"
    assert ans_res.ready_for_review is False


# --- Issue #59 Finding 2: per-sentence/clause first-person achievement claims ---


@pytest.mark.parametrize(
    "source_text",
    [
        "I led the PostgreSQL migration. My colleague led the Docker migration.",
        "I led the PostgreSQL migration, while my colleague led the Docker migration.",
        "I led the PostgreSQL migration, whereas my colleague led the Docker migration.",
        "I led the PostgreSQL migration, but my colleague led the Docker migration.",
        "I led the PostgreSQL migration, and my colleague led the Docker migration.",
        "I led the PostgreSQL migration and my colleague led the Docker migration.",
    ],
)
def test_cross_sentence_and_multi_clause_first_person_claim_rejected(source_text):
    for kwargs in (
        {"back": "I led the Docker migration."},
        {
            "back": "I led the PostgreSQL migration.",
            "explanation": "I led the Docker migration.",
        },
        {
            "back": "I led the PostgreSQL migration.",
            "accepted_answers": ["I led the Docker migration."],
        },
    ):
        result = evaluate_generated_card(
            front="Describe the migration ownership from the notes.",
            kind="behavioral",
            source_text=source_text,
            **kwargs,
        )
        assert result.checks.technical_accuracy == "fail"
        assert result.ready_for_review is False
        assert (
            "Card makes a first-person achievement claim not supported by source_text."
            in result.rejection_reasons
        )


def test_single_sentence_first_person_claim_passes_and_team_statement_rejects():
    valid = evaluate_generated_card(
        front="Which database migration did you lead?",
        back="I led the PostgreSQL migration.",
        kind="behavioral",
        source_text="I led the PostgreSQL migration. My colleague led the Docker migration.",
    )
    assert valid.checks.technical_accuracy == "pass"
    assert valid.ready_for_review is True

    unsupported_team = evaluate_generated_card(
        front="Which database migration did you lead?",
        back="I led the PostgreSQL migration.",
        kind="behavioral",
        source_text="Our team uses PostgreSQL for analytics workloads.",
    )
    assert unsupported_team.checks.technical_accuracy == "fail"
    assert unsupported_team.ready_for_review is False

    wrong_year = evaluate_generated_card(
        front="When did you lead the PostgreSQL migration?",
        back="I led the PostgreSQL migration in 2025.",
        kind="behavioral",
        source_text="I led the PostgreSQL migration in 2024.",
    )
    assert wrong_year.checks.technical_accuracy == "fail"
    assert wrong_year.ready_for_review is False

    glossary_not_expanded_for_claims = evaluate_generated_card(
        front="What did you build for PostgreSQL?",
        back="I built relational transactions.",
        kind="behavioral",
        source_text="I built PostgreSQL backups for staging.",
    )
    assert glossary_not_expanded_for_claims.checks.technical_accuracy == "fail"
    assert glossary_not_expanded_for_claims.ready_for_review is False


# --- Issue #59 Finding 3: bracketed placeholders & practice scaffold exemption ---


def test_placeholder_in_explanation_or_answers_never_exempts_first_person_claims():
    source_text = "Our team uses PostgreSQL for transactional storage."
    for kwargs in (
        {"explanation": "I led the PostgreSQL migration [project]."},
        {"accepted_answers": ["I led the PostgreSQL migration [project]."]},
    ):
        result = evaluate_generated_card(
            front="What database does the team use?",
            back="PostgreSQL supports transactional storage.",
            kind="sentence",
            source_text=source_text,
            **kwargs,
        )
        assert result.checks.technical_accuracy == "fail"
        assert result.ready_for_review is False
        assert any("placeholder" in item.lower() for item in result.uncertainty)


def test_placeholder_in_explanation_or_answers_without_claim_warns_ambiguity():
    source_text = "PostgreSQL supports transactional storage for cloud services."
    for kwargs in (
        {"explanation": "Use PostgreSQL transactions for [project] consistency."},
        {"accepted_answers": ["PostgreSQL transactions for [project] workloads."]},
    ):
        result = evaluate_generated_card(
            front="What database feature ensures PostgreSQL consistency?",
            back="PostgreSQL supports transactional storage.",
            kind="sentence",
            source_text=source_text,
            **kwargs,
        )
        assert result.status == "draft"
        assert result.ready_for_review is True
        assert result.checks.technical_accuracy == "pass"
        assert result.checks.ambiguity == "warn"
        assert any("placeholder" in item.lower() for item in result.uncertainty)


def test_practice_scaffold_exemption_scope():
    source_text = "Cloud support role working with AWS infrastructure."

    # Non-interview card with "Practice: I have worked with ..." is NOT exempted.
    non_interview = evaluate_generated_card(
        front="How do you describe AWS work?",
        back="Practice: I have worked with AWS to [project]. Use a truthful example.",
        kind="sentence",
        source_text=source_text,
    )
    assert non_interview.checks.technical_accuracy == "fail"

    # Interview card with concrete achievement verb in back is NOT exempted.
    concrete_claim = evaluate_generated_card(
        front="How would you discuss your experience with AWS?",
        back="Practice: I led AWS migrations for [project]. Use a truthful example.",
        kind="interview_phrase",
        source_text=source_text,
    )
    assert concrete_claim.checks.technical_accuracy == "fail"

    # Interview card without scaffold hint is NOT exempted.
    no_hint = evaluate_generated_card(
        front="How would you discuss your experience with AWS?",
        back="I have worked with AWS to configure cloud accounts.",
        kind="interview_phrase",
        source_text=source_text,
    )
    assert no_hint.checks.technical_accuracy == "fail"

    # Interview card claim in explanation or accepted_answers is NOT exempted.
    in_explanation = evaluate_generated_card(
        front="How would you discuss your experience with AWS?",
        back="Practice: I have worked with AWS to [task]. Use a truthful example.",
        kind="interview_phrase",
        explanation="Practice: I have worked with AWS to [project]. Use a truthful example.",
        source_text=source_text,
    )
    assert in_explanation.checks.technical_accuracy == "fail"

    in_answers = evaluate_generated_card(
        front="How would you discuss your experience with AWS?",
        back="Practice: I have worked with AWS to [task]. Use a truthful example.",
        kind="interview_phrase",
        accepted_answers=["Practice: I have worked with AWS to [project]. Use a truthful example."],
        source_text=source_text,
    )
    assert in_answers.checks.technical_accuracy == "fail"


# --- Cloze, 1-word, 2-char, listening, NUL, length, and field-level checks ---


def test_cloze_one_word_and_two_char_technical_answers():
    pg_res = evaluate_generated_card(
        front="PostgreSQL supports SQL and ____.",
        back="transactions",
        kind="cloze",
        source_text="PostgreSQL powers our transactional backend.",
    )
    assert pg_res.status == "draft"
    assert pg_res.checks.english_usefulness == "pass"
    assert pg_res.checks.source_grounding == "pass"
    assert pg_res.checks.ambiguity == "warn"

    ip_res = evaluate_generated_card(
        front="A route table matches the destination ____ prefix.",
        back="IP",
        kind="cloze",
        accepted_answers=["IP address"],
        source_text="VPC route tables inspect the destination IP prefix.",
    )
    assert ip_res.status == "draft"
    assert ip_res.checks.english_usefulness == "pass"
    assert ip_res.checks.source_grounding == "pass"
    assert ip_res.checks.ambiguity == "pass"

    bad_blank = evaluate_generated_card(
        front="A route table matches the destination IP prefix.",
        back="IP",
        kind="cloze",
        source_text="VPC route tables inspect the destination IP prefix.",
    )
    assert bad_blank.checks.ambiguity == "fail"
    assert bad_blank.ready_for_review is False

    one_char_back = evaluate_generated_card(
        front="Use ____ for routing tables.",
        back="a",
        kind="cloze",
        source_text="Use a routing table for subnets.",
    )
    assert one_char_back.checks.english_usefulness == "fail"


def test_nul_bytes_and_length_limits():
    source_text = "AWS Linux troubleshooting guide for cloud engineers."
    for kwargs in (
        {"front": "Explain\x00AWS", "back": "Cloud platform services."},
        {"front": "Explain AWS services", "back": "Cloud\x00platform."},
        {
            "front": "Explain AWS services",
            "back": "Cloud platform services.",
            "explanation": "A\x00B",
        },
        {
            "front": "Explain AWS services",
            "back": "Cloud platform services.",
            "accepted_answers": ["Cloud\x00services"],
        },
    ):
        res = evaluate_generated_card(kind="vocabulary", source_text=source_text, **kwargs)
        assert res.checks.english_usefulness == "fail"
        assert res.ready_for_review is False

    long_listening = evaluate_generated_card(
        front="Listen to the AWS troubleshooting briefing.",
        back="AWS " + ("troubleshooting " * 70),
        kind="listening",
        source_text=source_text,
    )
    assert long_listening.checks.english_usefulness == "fail"
    assert long_listening.ready_for_review is False

    over_5000 = evaluate_generated_card(
        front="Explain AWS troubleshooting.",
        back="AWS " + ("cloud " * 900),
        kind="vocabulary",
        source_text=source_text,
    )
    assert over_5000.checks.english_usefulness == "fail"


@pytest.mark.parametrize(
    ("source_text", "bad_text"),
    [
        ("AWS VPC security groups filter traffic.", "Security groups are stateless firewalls."),
        ("AWS VPC network ACLs filter subnet traffic.", "Network ACLs are stateful firewalls."),
        ("TCP delivers packets in order.", "TCP is a connectionless protocol."),
        ("UDP sends datagrams quickly.", "UDP uses a 3-way handshake."),
        ("IAM roles grant AWS access.", "IAM roles provide permanent credentials."),
        ("PostgreSQL stores relational tables.", "PostgreSQL is a NoSQL database."),
        ("Docker runs application containers.", "Docker is a hypervisor."),
        ("Python automates cloud tasks.", "Python is an operating system."),
        ("Linux runs cloud servers.", "Linux is a programming language."),
        ("Terraform provisions infrastructure.", "Terraform is a container runtime."),
    ],
)
def test_technical_contradictions_across_fields(source_text, bad_text):
    for field in ("back", "explanation", "accepted_answers"):
        kwargs = {
            "front": "Explain this cloud infrastructure concept.",
            "back": source_text,
            "kind": "vocabulary",
            "source_text": source_text,
        }
        if field == "back":
            kwargs["back"] = bad_text
        elif field == "explanation":
            kwargs["explanation"] = bad_text
        else:
            kwargs["accepted_answers"] = [bad_text]
        result = evaluate_generated_card(**kwargs)
        assert result.checks.technical_accuracy == "fail"
        assert result.ready_for_review is False


def test_explanation_and_accepted_answers_usefulness_ambiguity_grounding():
    source_text = "AWS VPC route tables direct subnet traffic to gateways."
    base = {
        "front": "What do AWS VPC route tables control?",
        "back": "Route tables direct subnet traffic to gateways.",
        "kind": "vocabulary",
        "source_text": source_text,
    }

    # Bare URL / too short in explanation and accepted_answers
    bad_exp = evaluate_generated_card(**base, explanation="https://example.com/vpc")
    assert bad_exp.checks.english_usefulness == "fail"
    assert bad_exp.checks.ambiguity == "fail"
    assert bad_exp.checks.source_grounding == "fail"

    bad_ans = evaluate_generated_card(**base, accepted_answers=["https://example.com/vpc"])
    assert bad_ans.checks.english_usefulness == "fail"
    assert bad_ans.checks.ambiguity == "fail"
    assert bad_ans.checks.source_grounding == "fail"

    # Front equality
    same_exp = evaluate_generated_card(**base, explanation=base["front"])
    assert same_exp.checks.ambiguity == "fail"

    same_ans = evaluate_generated_card(**base, accepted_answers=[base["front"]])
    assert same_ans.checks.ambiguity == "fail"

    # Unresolved markers
    todo_exp = evaluate_generated_card(**base, explanation="Route tables TBD for gateways.")
    assert todo_exp.checks.ambiguity == "fail"

    q_ans = evaluate_generated_card(**base, accepted_answers=["Route tables direct traffic ???"])
    assert q_ans.checks.ambiguity == "fail"

    # Ungrounded explanation / accepted_answers
    ungrounded_exp = evaluate_generated_card(
        **base, explanation="Baking sourdough bread takes overnight fermentation."
    )
    assert ungrounded_exp.checks.source_grounding == "fail"

    ungrounded_ans = evaluate_generated_card(
        **base, accepted_answers=["Baking sourdough bread overnight"]
    )
    assert ungrounded_ans.checks.source_grounding == "fail"


# --- API endpoints: /cards/generate/preview & /cards/generate/approve ---


def test_preview_returns_evaluated_drafts_without_persisting(client, db_engine):
    did = create_deck(client)
    resp = client.post(
        "/cards/generate/preview",
        json={
            "deck_id": did,
            "text": "Cloud support role using AWS, Linux, Python and troubleshooting.",
            "max_cards": 6,
            "source_label": "  vacancy:cloud-support  ",
        },
    )
    assert resp.status_code == 200
    drafts = resp.json()
    assert len(drafts) == 6
    assert all(d["deck_id"] == did for d in drafts)
    assert all(d["source_label"] == "vacancy:cloud-support" for d in drafts)
    assert all(d["evaluation"]["status"] == "draft" for d in drafts)
    assert all(d["evaluation"]["ready_for_review"] is True for d in drafts)

    interview_draft = next(d for d in drafts if d["kind"] == "interview_phrase")
    assert interview_draft["evaluation"]["checks"]["ambiguity"] == "warn"
    assert any("placeholder" in u.lower() for u in interview_draft["evaluation"]["uncertainty"])

    # Preview must persist zero cards.
    with Session(db_engine) as session:
        assert session.scalars(select(Card)).all() == []


def test_preview_rejects_fallback_generic_cards_and_handles_missing_deck(client):
    did = create_deck(client)
    resp = client.post(
        "/cards/generate/preview",
        json={
            "deck_id": did,
            "text": "Coordinate quarterly cross-team roadmap meetings and reviews.",
            "max_cards": 4,
            "source_label": "   ",
        },
    )
    assert resp.status_code == 200
    drafts = resp.json()
    assert len(drafts) == 2
    assert all(d["source_label"] is None for d in drafts)
    assert all(d["evaluation"]["status"] == "rejected" for d in drafts)
    assert all(d["evaluation"]["ready_for_review"] is False for d in drafts)
    assert all(d["evaluation"]["checks"]["source_grounding"] == "fail" for d in drafts)

    missing = client.post(
        "/cards/generate/preview",
        json={
            "deck_id": 99999,
            "text": "Cloud support role using AWS, Linux, Python and troubleshooting.",
        },
    )
    assert missing.status_code == 404


def test_preview_releases_db_transaction_before_generator_call(client, db_engine):
    did = create_deck(client)
    observed: dict[str, object] = {}
    active_sessions: list[Session] = []

    def tracking_db():
        with Session(db_engine) as session:
            active_sessions.append(session)
            yield session

    class CheckingGenerator:
        def generate(self, text: str, max_cards: int) -> list[GeneratedCard]:
            observed["in_transaction"] = active_sessions[-1].in_transaction()
            return [
                GeneratedCard(
                    front="Explain 'aws' in technical English.",
                    back="Amazon Web Services cloud platform.",
                    kind="vocabulary",
                )
            ]

    app.dependency_overrides[get_db] = tracking_db
    app.dependency_overrides[get_generator] = lambda: CheckingGenerator()
    try:
        resp = client.post(
            "/cards/generate/preview",
            json={"deck_id": did, "text": "Cloud support role using AWS and Linux."},
        )
    finally:
        app.dependency_overrides.pop(get_generator, None)

    assert resp.status_code == 200
    assert observed["in_transaction"] is False


def test_preview_handles_empty_generator_and_deleted_deck_during_generation(client, db_engine):
    did = create_deck(client)

    class EmptyGenerator:
        def generate(self, text: str, max_cards: int) -> list[GeneratedCard]:
            return []

    app.dependency_overrides[get_generator] = lambda: EmptyGenerator()
    try:
        resp = client.post(
            "/cards/generate/preview",
            json={"deck_id": did, "text": "Cloud support role using AWS and Linux."},
        )
    finally:
        app.dependency_overrides.pop(get_generator, None)
    assert resp.status_code == 502

    class DeletingGenerator:
        def generate(self, text: str, max_cards: int) -> list[GeneratedCard]:
            with Session(db_engine) as s:
                deck = s.get(Deck, did)
                if deck is not None:
                    s.delete(deck)
                    s.commit()
            return [
                GeneratedCard(
                    front="Explain 'aws' in technical English.",
                    back="Amazon Web Services cloud platform.",
                    kind="vocabulary",
                )
            ]

    app.dependency_overrides[get_generator] = lambda: DeletingGenerator()
    try:
        resp = client.post(
            "/cards/generate/preview",
            json={"deck_id": did, "text": "Cloud support role using AWS and Linux."},
        )
    finally:
        app.dependency_overrides.pop(get_generator, None)
    assert resp.status_code == 404


def test_approve_persists_valid_draft_and_rejects_failed_draft(client, db_engine, set_clock):
    set_clock(datetime(2026, 11, 27, 15, 0, 0, tzinfo=UTC))
    did = create_deck(client)

    # Valid edited draft -> 201 and persisted.
    ok_resp = client.post(
        "/cards/generate/approve",
        json={
            "deck_id": did,
            "front": "VPC route tables match destination ____ CIDR blocks.",
            "back": "IP",
            "kind": "cloze",
            "source_label": "  aws-docs:vpc  ",
            "accepted_answers": ["IP address"],
            "explanation": "Route tables inspect destination IP CIDR blocks.",
            "source_text": "AWS VPC route tables match destination IP CIDR blocks.",
        },
    )
    assert ok_resp.status_code == 201
    body = ok_resp.json()
    assert body["card"]["deck_id"] == did
    assert body["card"]["front"] == "VPC route tables match destination ____ CIDR blocks."
    assert body["card"]["back"] == "IP"
    assert body["card"]["source_label"] == "aws-docs:vpc"
    assert body["card"]["accepted_answers"] == ["IP address"]
    assert body["card"]["due_date"] == "2026-11-27"
    assert body["evaluation"]["status"] == "draft"
    assert body["evaluation"]["ready_for_review"] is True

    # Rejected draft (contradiction / ungrounded metric) -> 422, no new row persisted.
    bad_resp = client.post(
        "/cards/generate/approve",
        json={
            "deck_id": did,
            "front": "How do AWS security groups filter traffic?",
            "back": "AWS security groups are stateless firewalls and saved $50,000.",
            "kind": "vocabulary",
            "source_text": "AWS VPC security groups act as stateful virtual firewalls.",
        },
    )
    assert bad_resp.status_code == 422
    assert "stateful" in bad_resp.json()["detail"].lower()

    with Session(db_engine) as session:
        cards = session.scalars(select(Card)).all()
        assert len(cards) == 1
        assert cards[0].id == body["card"]["id"]

    # Missing deck -> 404
    missing = client.post(
        "/cards/generate/approve",
        json={
            "deck_id": 99999,
            "front": "Explain 'aws' in technical English.",
            "back": "Amazon Web Services cloud platform.",
            "kind": "vocabulary",
            "source_text": "Cloud support role using AWS and Linux.",
        },
    )
    assert missing.status_code == 404


def test_approve_rejects_nul_bytes_and_handles_commit_integrity_error(client):
    did = create_deck(client)
    for bad_payload in (
        {
            "deck_id": did,
            "front": "Explain AWS cloud.",
            "back": "Amazon Web Services cloud platform.",
            "source_label": "aws\x00label",
            "source_text": "Cloud support role using AWS and Linux.",
        },
        {
            "deck_id": did,
            "front": "Explain AWS cloud.",
            "back": "Amazon Web Services cloud platform.",
            "source_text": "Cloud support role using\x00AWS and Linux.",
        },
    ):
        resp = client.post("/cards/generate/approve", json=bad_payload)
        assert resp.status_code == 422

    # Simulate FK race on commit -> 404 Deck not found.
    with patch.object(Session, "commit", side_effect=IntegrityError("INSERT", {}, Exception("fk"))):
        raced = client.post(
            "/cards/generate/approve",
            json={
                "deck_id": did,
                "front": "Explain 'aws' in technical English.",
                "back": "Amazon Web Services cloud platform.",
                "kind": "vocabulary",
                "source_text": "Cloud support role using AWS and Linux.",
            },
        )
    assert raced.status_code == 404
    assert raced.json()["detail"] == "Deck not found"


def test_preview_rejects_nul_bytes_in_text_or_source_label(client):
    did = create_deck(client)
    for payload in (
        {"deck_id": did, "text": "Cloud support\x00role using AWS and Linux."},
        {
            "deck_id": did,
            "text": "Cloud support role using AWS and Linux.",
            "source_label": "bad\x00label",
        },
    ):
        resp = client.post("/cards/generate/preview", json=payload)
        assert resp.status_code == 422


# --- Sol Round 1 regressions: reversed claims & practice exemption abuse ---


def test_reversed_metric_and_directional_claims_rejected(client, db_engine):
    did = create_deck(client)
    source_text = "I reduced AWS latency from 200ms to 100ms."

    valid = evaluate_generated_card(
        front="How did you improve AWS latency?",
        back="I reduced AWS latency from 200ms to 100ms.",
        kind="behavioral",
        source_text=source_text,
    )
    assert valid.checks.technical_accuracy == "pass"
    assert valid.ready_for_review is True

    for bad_back in (
        "I reduced AWS latency from 100ms to 200ms.",
        "I reduced AWS latency to 200ms.",
    ):
        res = evaluate_generated_card(
            front="How did you improve AWS latency?",
            back=bad_back,
            kind="behavioral",
            source_text=source_text,
        )
        assert res.checks.technical_accuracy == "fail"
        assert res.ready_for_review is False
        assert (
            "Card makes a first-person achievement claim not supported by source_text."
            in res.rejection_reasons
        )

        resp = client.post(
            "/cards/generate/approve",
            json={
                "deck_id": did,
                "front": "How did you improve AWS latency?",
                "back": bad_back,
                "kind": "behavioral",
                "source_text": source_text,
            },
        )
        assert resp.status_code == 422

    with Session(db_engine) as session:
        assert session.scalars(select(Card)).all() == []


def test_reversed_technology_claim_rejected():
    source_text = "I migrated our API from PostgreSQL to Docker."

    valid = evaluate_generated_card(
        front="Which API migration did you perform?",
        back="I migrated our API from PostgreSQL to Docker.",
        kind="behavioral",
        source_text=source_text,
    )
    assert valid.checks.technical_accuracy == "pass"
    assert valid.ready_for_review is True

    reversed_claim = evaluate_generated_card(
        front="Which API migration did you perform?",
        back="I migrated our API from Docker to PostgreSQL.",
        kind="behavioral",
        source_text=source_text,
    )
    assert reversed_claim.checks.technical_accuracy == "fail"
    assert reversed_claim.ready_for_review is False
    assert (
        "Card makes a first-person achievement claim not supported by source_text."
        in reversed_claim.rejection_reasons
    )


def test_practice_exemption_abuse_rejected(client, db_engine):
    did = create_deck(client)
    source_text = "Cloud support role working with AWS infrastructure."

    genuine = evaluate_generated_card(
        front="How would you discuss your experience with AWS?",
        back=(
            "Practice: I have worked with AWS to [task]. "
            "Use a truthful example and explain your contribution."
        ),
        kind="interview_phrase",
        source_text=source_text,
    )
    assert genuine.checks.technical_accuracy == "pass"
    assert genuine.ready_for_review is True

    for abused_back in (
        "Practice: I have worked with AWS to lead the production migration",
        (
            "Practice: I have worked with AWS to lead the production migration [task]. "
            "Use a truthful example and explain your contribution."
        ),
    ):
        res = evaluate_generated_card(
            front="How would you discuss your experience with AWS?",
            back=abused_back,
            kind="interview_phrase",
            source_text=source_text,
        )
        assert res.checks.technical_accuracy == "fail"
        assert res.ready_for_review is False
        assert (
            "Card makes a first-person achievement claim not supported by source_text."
            in res.rejection_reasons
        )

        resp = client.post(
            "/cards/generate/approve",
            json={
                "deck_id": did,
                "front": "How would you discuss your experience with AWS?",
                "back": abused_back,
                "kind": "interview_phrase",
                "source_text": source_text,
            },
        )
        assert resp.status_code == 422

    with Session(db_engine) as session:
        assert session.scalars(select(Card)).all() == []


# --- Sol Round 2 regressions: cross-metric binding & subject-less coordinated verbs ---


def test_cross_metric_target_assignment_rejected(client, db_engine):
    did = create_deck(client)
    source_text = (
        "I reduced AWS latency from 200ms to 100ms and database latency from 300ms to 200ms."
    )

    for valid_back in (
        "I reduced AWS latency from 200ms to 100ms.",
        "I reduced database latency from 300ms to 200ms.",
    ):
        res = evaluate_generated_card(
            front="How did you improve latency?",
            back=valid_back,
            kind="behavioral",
            source_text=source_text,
        )
        assert res.checks.technical_accuracy == "pass"
        assert res.ready_for_review is True

    for bad_back in (
        "I reduced AWS latency to 200ms.",
        "I reduced database latency to 100ms.",
    ):
        res = evaluate_generated_card(
            front="How did you improve latency?",
            back=bad_back,
            kind="behavioral",
            source_text=source_text,
        )
        assert res.checks.technical_accuracy == "fail"
        assert res.ready_for_review is False
        assert (
            "Card makes a first-person achievement claim not supported by source_text."
            in res.rejection_reasons
        )

        resp = client.post(
            "/cards/generate/approve",
            json={
                "deck_id": did,
                "front": "How did you improve latency?",
                "back": bad_back,
                "kind": "behavioral",
                "source_text": source_text,
            },
        )
        assert resp.status_code == 422

    with Session(db_engine) as session:
        assert session.scalars(select(Card)).all() == []


def test_coordinated_count_swap_rejected():
    source_text = "I migrated 10 AWS services and 5 GCP services."

    for valid_back in (
        "I migrated 10 AWS services.",
        "I migrated 5 GCP services.",
    ):
        res = evaluate_generated_card(
            front="How many cloud services did you migrate?",
            back=valid_back,
            kind="behavioral",
            source_text=source_text,
        )
        assert res.checks.technical_accuracy == "pass"
        assert res.ready_for_review is True

    swapped = evaluate_generated_card(
        front="How many AWS services did you migrate?",
        back="I migrated 5 AWS services.",
        kind="behavioral",
        source_text=source_text,
    )
    assert swapped.checks.technical_accuracy == "fail"
    assert swapped.ready_for_review is False
    assert (
        "Card makes a first-person achievement claim not supported by source_text."
        in swapped.rejection_reasons
    )


def test_subjectless_coordinated_verb_in_practice_and_regular_back_rejected(client, db_engine):
    did = create_deck(client)

    cases = (
        (
            "Cloud support role using AWS. My colleague led production migrations.",
            "How would you discuss your experience with AWS?",
            (
                "Practice: I have worked with AWS to [task], and led production migrations. "
                "Use a truthful example."
            ),
            "interview_phrase",
        ),
        (
            "I worked with AWS. My colleague led production migrations.",
            "What production work did you handle with AWS?",
            "I worked with AWS, and led production migrations.",
            "behavioral",
        ),
    )

    for source_text, front, bad_back, kind in cases:
        res = evaluate_generated_card(
            front=front,
            back=bad_back,
            kind=kind,
            source_text=source_text,
        )
        assert res.checks.technical_accuracy == "fail"
        assert res.ready_for_review is False
        assert (
            "Card makes a first-person achievement claim not supported by source_text."
            in res.rejection_reasons
        )

        resp = client.post(
            "/cards/generate/approve",
            json={
                "deck_id": did,
                "front": front,
                "back": bad_back,
                "kind": kind,
                "source_text": source_text,
            },
        )
        assert resp.status_code == 422

    with Session(db_engine) as session:
        assert session.scalars(select(Card)).all() == []
