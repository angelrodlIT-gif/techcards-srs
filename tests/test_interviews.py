from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect
from sqlalchemy import text as sa_text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

import app.main as main_module
from app.config import get_settings
from app.interview import (
    NON_BEHAVIORAL_STAR_NOTE,
    MockInterviewEvaluator,
    TurnFeedback,
    build_turn_prompt,
    get_interview_evaluator,
)
from app.main import app
from app.models import InterviewSession, InterviewTurn, Source


def create_source(client, label="AWS Support JD", status="draft"):
    resp = client.post("/sources", json={"label": label, "excerpt": "Cloud support basics"})
    assert resp.status_code == 201
    source_id = resp.json()["id"]
    if status == "discarded":
        disc = client.post(f"/sources/{source_id}/discard")
        assert disc.status_code == 200
    elif status == "approved":
        deck_id = client.post("/decks", json={"name": "Interview Deck"}).json()["id"]
        appr = client.post(
            f"/sources/{source_id}/approve",
            json={"deck_id": deck_id, "front": "What is IAM?", "back": "Access management"},
        )
        assert appr.status_code == 201
    return source_id


@pytest.mark.parametrize("role", ["cloud_support", "junior_aws", "python_backend"])
def test_create_session_for_all_roles(client, set_clock, role):
    created_at = datetime(2026, 7, 1, 14, 30, 0, tzinfo=UTC)
    set_clock(created_at)

    resp = client.post("/interviews", json={"role": role})
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == role
    assert body["source_id"] is None
    assert body["status"] == "active"
    assert body["completed_at"] is None
    assert body["created_at"].startswith("2026-07-01T14:30:00")

    turns = body["turns"]
    assert [(t["turn_index"], t["turn_type"]) for t in turns] == [
        (1, "technical"),
        (2, "follow_up"),
        (3, "behavioral"),
    ]
    for turn in turns:
        assert turn["session_id"] == body["id"]
        assert turn["answer"] is None
        assert turn["english_clarity"] is None
        assert turn["technical_accuracy"] is None
        assert turn["star_structure"] is None
        assert turn["corrected_phrasing"] is None
        assert turn["uncertainty_note"] is None
        assert turn["human_review_status"] == "pending"
        assert turn["human_notes"] is None

    behavioral_prompt = turns[2]["prompt"].lower()
    assert "star" in behavioral_prompt
    assert "real experience" in behavioral_prompt
    assert "do not invent" in behavioral_prompt

    fetched = client.get(f"/interviews/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_source_linking_errors_and_on_delete_set_null(client):
    assert client.post("/interviews", json={"role": "unknown_role"}).status_code == 422
    assert (
        client.post("/interviews", json={"role": "cloud_support", "source_id": 0}).status_code
        == 422
    )
    assert (
        client.post("/interviews", json={"role": "cloud_support", "source_id": -5}).status_code
        == 422
    )
    assert (
        client.post("/interviews", json={"role": "cloud_support", "source_id": 999}).status_code
        == 404
    )

    discarded_id = create_source(client, label="Old JD", status="discarded")
    assert (
        client.post(
            "/interviews", json={"role": "junior_aws", "source_id": discarded_id}
        ).status_code
        == 409
    )

    draft_source_id = create_source(client, label="AWS Cloud Support Posting", status="draft")
    approved_source_id = create_source(client, label="Python Backend Posting", status="approved")

    s1 = client.post("/interviews", json={"role": "cloud_support", "source_id": draft_source_id})
    assert s1.status_code == 201
    s1_body = s1.json()
    assert s1_body["source_id"] == draft_source_id
    for turn in s1_body["turns"]:
        assert turn["prompt"].startswith("[Source: AWS Cloud Support Posting] ")

    s2 = client.post(
        "/interviews", json={"role": "python_backend", "source_id": approved_source_id}
    )
    assert s2.status_code == 201
    assert s2.json()["turns"][0]["prompt"].startswith("[Source: Python Backend Posting] ")

    # Deleting a linked source sets interview_sessions.source_id to NULL while keeping the session.
    assert client.delete(f"/sources/{draft_source_id}").status_code == 204
    re_read = client.get(f"/interviews/{s1_body['id']}")
    assert re_read.status_code == 200
    assert re_read.json()["source_id"] is None
    assert len(re_read.json()["turns"]) == 3


def test_sequential_answering_rubric_corrections_and_completion(client, set_clock):
    set_clock(datetime(2026, 7, 2, 10, 0, 0, tzinfo=UTC))
    session = client.post("/interviews", json={"role": "cloud_support"}).json()
    sid = session["id"]
    t1, t2, t3 = session["turns"]

    # Out-of-order answers and premature completion are rejected with 409.
    assert (
        client.post(
            f"/interviews/{sid}/turns/{t2['id']}/answer", json={"answer": "Check metrics."}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/interviews/{sid}/turns/{t3['id']}/answer", json={"answer": "Situation and result."}
        ).status_code
        == 409
    )
    assert client.post(f"/interviews/{sid}/complete").status_code == 409

    # Input validation on answer.
    for bad in ("   ", "Bad\x00answer", "x" * 5001):
        assert (
            client.post(
                f"/interviews/{sid}/turns/{t1['id']}/answer", json={"answer": bad}
            ).status_code
            == 422
        )

    # Missing session/turn or mismatched session/turn -> 404.
    other = client.post("/interviews", json={"role": "junior_aws"}).json()
    assert (
        client.post(
            f"/interviews/999/turns/{t1['id']}/answer", json={"answer": "Check logs."}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/interviews/{sid}/turns/999/answer", json={"answer": "Check logs."}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/interviews/{sid}/turns/{other['turns'][0]['id']}/answer",
            json={"answer": "Wrong session."},
        ).status_code
        == 404
    )

    # Turn 1 (technical): triggers B2 phrasing corrections and rubric separation.
    ans1 = (
        "  First, I make a troubleshooting by checking ALB logs and target health checks. "
        "The timeout can depend of security group rules. Explain me if you want more detail.  "
    )
    r1 = client.post(f"/interviews/{sid}/turns/{t1['id']}/answer", json={"answer": ans1})
    assert r1.status_code == 200
    fb1 = r1.json()
    assert fb1["answer"] == ans1.strip()
    assert fb1["human_review_status"] == "pending"
    assert "depend of" in fb1["english_clarity"] and "depend on" in fb1["english_clarity"]
    assert "Explain me" in fb1["english_clarity"] and "Explain to me" in fb1["english_clarity"]
    assert "make a troubleshooting" in fb1["english_clarity"]
    assert (
        fb1["corrected_phrasing"]
        == "First, I troubleshoot by checking ALB logs and target health checks. "
        "The timeout can depend on security group rules. Explain to me if you want more detail."
    )
    assert (
        "Mentioned: logs, health check, security group, timeout, target;"
        in fb1["technical_accuracy"]
    )
    assert "Consider covering: none." in fb1["technical_accuracy"]
    assert fb1["star_structure"] == NON_BEHAVIORAL_STAR_NOTE
    uncertainty = fb1["uncertainty_note"].lower()
    assert "offline text-mode heuristic" in uncertainty
    assert "human review" in uncertainty
    assert "no hiring or cefr" in uncertainty

    # Duplicate answer on turn 1 -> 409.
    assert (
        client.post(
            f"/interviews/{sid}/turns/{t1['id']}/answer", json={"answer": "Second attempt."}
        ).status_code
        == 409
    )

    # Turn 2 (follow_up): partial key concepts, no B2 patterns.
    r2 = client.post(
        f"/interviews/{sid}/turns/{t2['id']}/answer",
        json={
            "answer": (
                "I would check database latency metrics and reproduce the slow query "
                "before proposing any change."
            )
        },
    )
    assert r2.status_code == 200
    fb2 = r2.json()
    assert "Mentioned: metrics, database, latency, reproduce;" in fb2["technical_accuracy"]
    assert "Consider covering: verify." in fb2["technical_accuracy"]
    assert fb2["star_structure"] == NON_BEHAVIORAL_STAR_NOTE
    assert "No rule-based B2 phrasing issues matched" in fb2["english_clarity"]

    # Still incomplete before turn 3.
    assert client.post(f"/interviews/{sid}/complete").status_code == 409

    # Turn 3 (behavioral): STAR signposts checked and truthfulness reminder included.
    r3 = client.post(
        f"/interviews/{sid}/turns/{t3['id']}/answer",
        json={
            "answer": (
                "Situation: during a deployment, API errors spiked. "
                "My task was to coordinate communication with the team. "
                "Action: I checked logs to find the root cause and documented the handoff."
            )
        },
    )
    assert r3.status_code == 200
    fb3 = r3.json()
    assert "STAR components signposted: situation, task, action;" in fb3["star_structure"]
    assert "Missing or implicit: result." in fb3["star_structure"]
    assert "do not invent outcomes or metrics" in fb3["star_structure"].lower()
    assert "Mentioned: communication, root cause, handoff;" in fb3["technical_accuracy"]
    assert "Consider covering: resolution." in fb3["technical_accuracy"]

    # Complete the session now that all 3 turns are answered.
    completed_at = datetime(2026, 7, 2, 10, 15, 0, tzinfo=UTC)
    set_clock(completed_at)
    comp = client.post(f"/interviews/{sid}/complete")
    assert comp.status_code == 200
    comp_body = comp.json()
    assert comp_body["status"] == "completed"
    assert comp_body["completed_at"].startswith("2026-07-02T10:15:00")
    assert [t["turn_index"] for t in comp_body["turns"]] == [1, 2, 3]

    # Re-completing or answering after completion -> 409.
    assert client.post(f"/interviews/{sid}/complete").status_code == 409
    assert (
        client.post(
            f"/interviews/{sid}/turns/{t1['id']}/answer", json={"answer": "Too late."}
        ).status_code
        == 409
    )


def test_human_review_workflow(client):
    session = client.post("/interviews", json={"role": "python_backend"}).json()
    sid = session["id"]
    t1, t2, t3 = session["turns"]

    # Reviewing before answering -> 409; missing session/turn -> 404.
    assert (
        client.post(
            f"/interviews/{sid}/turns/{t1['id']}/review",
            json={"human_review_status": "accepted"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/interviews/999/turns/{t1['id']}/review",
            json={"human_review_status": "accepted"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/interviews/{sid}/turns/999/review",
            json={"human_review_status": "accepted"},
        ).status_code
        == 404
    )

    # Answer all 3 turns.
    ans1 = client.post(
        f"/interviews/{sid}/turns/{t1['id']}/answer",
        json={"answer": "The fix consist in adding a database transaction and unique constraint."},
    ).json()
    assert "consist of" in ans1["corrected_phrasing"]

    client.post(
        f"/interviews/{sid}/turns/{t2['id']}/answer",
        json={"answer": "I check index coverage, query timeout, and write an automated test."},
    )
    client.post(
        f"/interviews/{sid}/turns/{t3['id']}/answer",
        json={
            "answer": (
                "Situation: code review flagged a trade-off. Task: add tests. "
                "Action: I fixed the query. Result: clear outcome."
            )
        },
    )

    # Validation errors on review payload.
    for bad_review in (
        {"human_review_status": "pending"},
        {"human_review_status": "invalid"},
        {"human_review_status": "edited", "corrected_phrasing": "   "},
        {"human_review_status": "edited", "corrected_phrasing": "Bad\x00phrase"},
        {"human_review_status": "accepted", "human_notes": "Bad\x00note"},
    ):
        assert (
            client.post(f"/interviews/{sid}/turns/{t1['id']}/review", json=bad_review).status_code
            == 422
        )

    # Accept turn 1 with notes; corrected_phrasing stays intact.
    rev1 = client.post(
        f"/interviews/{sid}/turns/{t1['id']}/review",
        json={"human_review_status": "accepted", "human_notes": "  Helpful preposition fix.  "},
    )
    assert rev1.status_code == 200
    assert rev1.json()["human_review_status"] == "accepted"
    assert rev1.json()["human_notes"] == "Helpful preposition fix."
    assert rev1.json()["corrected_phrasing"] == ans1["corrected_phrasing"]

    # Edit turn 1 with a custom phrasing while omitting human_notes -> keeps previous notes.
    rev1_edit = client.post(
        f"/interviews/{sid}/turns/{t1['id']}/review",
        json={
            "human_review_status": "edited",
            "corrected_phrasing": "The fix consists of wrapping the write in a transaction.",
        },
    )
    assert rev1_edit.status_code == 200
    assert rev1_edit.json()["human_review_status"] == "edited"
    assert (
        rev1_edit.json()["corrected_phrasing"]
        == "The fix consists of wrapping the write in a transaction."
    )
    assert rev1_edit.json()["human_notes"] == "Helpful preposition fix."

    # Explicitly passing blank human_notes clears it.
    rev1_clear = client.post(
        f"/interviews/{sid}/turns/{t1['id']}/review",
        json={"human_review_status": "edited", "human_notes": "   "},
    )
    assert rev1_clear.status_code == 200
    assert rev1_clear.json()["human_notes"] is None

    # Dismiss turn 2 (even if corrected_phrasing is passed, dismiss does not overwrite it).
    before_t2 = client.get(f"/interviews/{sid}").json()["turns"][1]["corrected_phrasing"]
    rev2 = client.post(
        f"/interviews/{sid}/turns/{t2['id']}/review",
        json={
            "human_review_status": "dismissed",
            "corrected_phrasing": "Should not overwrite",
            "human_notes": "Original phrasing was fine.",
        },
    )
    assert rev2.status_code == 200
    assert rev2.json()["human_review_status"] == "dismissed"
    assert rev2.json()["corrected_phrasing"] == before_t2
    assert rev2.json()["human_notes"] == "Original phrasing was fine."

    # Complete session, then confirm turn 3 can still be reviewed afterwards.
    assert client.post(f"/interviews/{sid}/complete").status_code == 200
    rev3 = client.post(
        f"/interviews/{sid}/turns/{t3['id']}/review",
        json={"human_review_status": "accepted", "human_notes": "Post-session review."},
    )
    assert rev3.status_code == 200
    assert rev3.json()["human_review_status"] == "accepted"


def test_list_filters_pagination_and_delete_cascade(client, db_engine):
    assert client.get("/interviews").json() == []
    assert client.get("/interviews/999").status_code == 404
    assert client.delete("/interviews/999").status_code == 404
    assert client.post("/interviews/999/complete").status_code == 404

    s1 = client.post("/interviews", json={"role": "cloud_support"}).json()
    s2 = client.post("/interviews", json={"role": "junior_aws"}).json()
    s3 = client.post("/interviews", json={"role": "cloud_support"}).json()

    for turn in s1["turns"]:
        assert (
            client.post(
                f"/interviews/{s1['id']}/turns/{turn['id']}/answer",
                json={"answer": "Detailed answer covering logs and verification."},
            ).status_code
            == 200
        )
    assert client.post(f"/interviews/{s1['id']}/complete").status_code == 200

    all_sessions = client.get("/interviews").json()
    assert [s["id"] for s in all_sessions] == [s1["id"], s2["id"], s3["id"]]
    assert all([t["turn_index"] for t in s["turns"]] == [1, 2, 3] for s in all_sessions)

    assert [
        s["id"] for s in client.get("/interviews", params={"role": "cloud_support"}).json()
    ] == [s1["id"], s3["id"]]
    assert [s["id"] for s in client.get("/interviews", params={"status": "completed"}).json()] == [
        s1["id"]
    ]
    assert [
        s["id"]
        for s in client.get(
            "/interviews", params={"role": "cloud_support", "status": "active"}
        ).json()
    ] == [s3["id"]]
    assert [
        s["id"] for s in client.get("/interviews", params={"offset": 1, "limit": 1}).json()
    ] == [s2["id"]]

    assert client.get("/interviews", params={"role": "invalid"}).status_code == 422
    assert client.get("/interviews", params={"status": "invalid"}).status_code == 422
    assert client.get("/interviews", params={"limit": 101}).status_code == 422

    # Delete cascades to interview_turns.
    assert client.delete(f"/interviews/{s1['id']}").status_code == 204
    assert client.get(f"/interviews/{s1['id']}").status_code == 404
    with Session(db_engine) as db:
        remaining = db.query(InterviewTurn).filter(InterviewTurn.session_id == s1["id"]).count()
        assert remaining == 0


def test_evaluator_whole_word_boundaries_and_seam_override(client, monkeypatch):
    evaluator = MockInterviewEvaluator()
    # Substring traps must not trigger false matches ("independent office", "diagram", "catalog").
    fb = evaluator.evaluate(
        role="junior_aws",
        turn_index=2,
        turn_type="follow_up",
        prompt="Prompt",
        answer="Our independent office reviewed a diagram and catalog without changing policies.",
    )
    assert "No rule-based B2 phrasing issues matched" in fb.english_clarity
    assert "depend on" not in fb.corrected_phrasing
    assert "Mentioned: policy;" in fb.technical_accuracy
    assert "iam" in fb.technical_accuracy.split("Consider covering:")[1]
    assert "no hiring or cefr" in fb.uncertainty_note.lower()

    # Prompt length bound check.
    with pytest.raises(ValueError):
        build_turn_prompt("x" * 5001)

    # Pluggable evaluator seam via dependency override.
    class FakeEvaluator:
        def evaluate(self, role, turn_index, turn_type, prompt, answer):
            return TurnFeedback(
                english_clarity=f"Custom clarity for {role} turn {turn_index}",
                technical_accuracy="Custom technical check",
                star_structure="Custom STAR check",
                corrected_phrasing=answer,
                uncertainty_note="Custom uncertainty note requiring human review.",
            )

    app.dependency_overrides[get_interview_evaluator] = FakeEvaluator
    session = client.post("/interviews", json={"role": "junior_aws"}).json()
    t1 = session["turns"][0]
    answered = client.post(
        f"/interviews/{session['id']}/turns/{t1['id']}/answer",
        json={"answer": "Check VPC route tables."},
    )
    assert answered.status_code == 200
    assert answered.json()["english_clarity"] == "Custom clarity for junior_aws turn 1"

    # Invalid provider setting is rejected by get_interview_evaluator().
    app.dependency_overrides.pop(get_interview_evaluator, None)
    monkeypatch.setenv("GENERATOR_PROVIDER", "unsupported-provider")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            get_interview_evaluator()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_interviews_migration_round_trip(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / 'interviews_migration.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()

    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "migrations"))
    engine = create_engine(db_url)
    try:
        command.upgrade(cfg, "0005")
        tables_before = set(inspect(engine).get_table_names())
        assert "interview_sessions" not in tables_before
        assert "interview_turns" not in tables_before
        with engine.begin() as conn:
            conn.execute(
                sa_text("INSERT INTO sources (id, label, status) VALUES (1, 'Cloud JD', 'draft')")
            )

        command.upgrade(cfg, "head")
        tables_after = set(inspect(engine).get_table_names())
        assert {"interview_sessions", "interview_turns"}.issubset(tables_after)
        turn_indexes = {idx["name"]: idx for idx in inspect(engine).get_indexes("interview_turns")}
        assert "ix_interview_turns_session_id" in turn_indexes
        assert turn_indexes["uq_interview_turns_session_turn"]["unique"]
        command.check(cfg)

        with engine.begin() as conn:
            conn.execute(
                sa_text(
                    "INSERT INTO interview_sessions (id, role, source_id, status, created_at) "
                    "VALUES (1, 'cloud_support', 1, 'active', '2026-07-01T00:00:00+00:00')"
                )
            )
            conn.execute(
                sa_text(
                    "INSERT INTO interview_turns (id, session_id, turn_index, turn_type, prompt, "
                    "human_review_status) VALUES (1, 1, 1, 'technical', 'Prompt', 'pending')"
                )
            )

        command.downgrade(cfg, "0005")
        tables_downgraded = set(inspect(engine).get_table_names())
        assert "interview_sessions" not in tables_downgraded
        assert "interview_turns" not in tables_downgraded
        with engine.connect() as conn:
            label = conn.execute(sa_text("SELECT label FROM sources WHERE id = 1")).scalar_one()
            assert label == "Cloud JD"

        command.upgrade(cfg, "head")
        assert {"interview_sessions", "interview_turns"}.issubset(
            set(inspect(engine).get_table_names())
        )
        command.check(cfg)
    finally:
        engine.dispose()
        monkeypatch.undo()
        get_settings.cache_clear()


def test_create_interview_locks_source_and_handles_concurrent_source_delete(
    client, db_engine, monkeypatch
):
    source_id = create_source(client, label="Concurrent JD", status="draft")

    pg_dialect = postgresql.dialect()
    scalar_queries: list[str] = []
    real_scalar = Session.scalar

    def record_scalar(self, statement, *args, **kwargs):
        scalar_queries.append(str(statement.compile(dialect=pg_dialect)).upper())
        return real_scalar(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "scalar", record_scalar)
    created = client.post("/interviews", json={"role": "cloud_support", "source_id": source_id})
    assert created.status_code == 201
    assert any("FROM SOURCES" in sql and "FOR UPDATE" in sql for sql in scalar_queries)
    monkeypatch.undo()

    # On SQLite (where FOR UPDATE is a no-op), simulate a peer deleting the source between
    # the source lookup and the session insert: FK IntegrityError must map cleanly to 404.
    if db_engine.dialect.name == "sqlite":
        raced_source_id = create_source(client, label="Raced JD", status="draft")
        real_get_role_track = main_module.get_role_track

        def delete_source_before_insert(role):
            with Session(db_engine) as peer:
                peer_source = peer.get(Source, raced_source_id)
                assert peer_source is not None
                peer.delete(peer_source)
                peer.commit()
            return real_get_role_track(role)

        monkeypatch.setattr(main_module, "get_role_track", delete_source_before_insert)
        resp = client.post(
            "/interviews", json={"role": "cloud_support", "source_id": raced_source_id}
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Source not found"

        with Session(db_engine) as db:
            assert (
                db.query(InterviewSession)
                .filter(InterviewSession.source_id == raced_source_id)
                .count()
                == 0
            )


def test_delete_interview_locks_session_before_deleting_turns(client, db_engine, monkeypatch):
    session = client.post("/interviews", json={"role": "cloud_support"}).json()
    sid = session["id"]
    t1 = session["turns"][0]
    assert (
        client.post(
            f"/interviews/{sid}/turns/{t1['id']}/answer",
            json={"answer": "Check ALB target health and security groups."},
        ).status_code
        == 200
    )

    pg_dialect = postgresql.dialect()
    events: list[str] = []
    real_scalar = Session.scalar

    def record_scalar(self, statement, *args, **kwargs):
        sql = str(statement.compile(dialect=pg_dialect)).upper()
        if "FROM INTERVIEW_SESSIONS" in sql and "FOR UPDATE" in sql:
            events.append("lock_session")
        return real_scalar(self, statement, *args, **kwargs)

    def on_sql(_conn, _cursor, statement, _params, _context, _executemany):
        sql = statement.upper()
        if "DELETE FROM INTERVIEW_TURNS" in sql:
            events.append("delete_turns")
        elif "DELETE FROM INTERVIEW_SESSIONS" in sql:
            events.append("delete_session")

    monkeypatch.setattr(Session, "scalar", record_scalar)
    event.listen(db_engine, "before_cursor_execute", on_sql)
    try:
        resp = client.delete(f"/interviews/{sid}")
    finally:
        event.remove(db_engine, "before_cursor_execute", on_sql)

    assert resp.status_code == 204
    assert events
    assert events[0] == "lock_session"
    assert "delete_session" in events
    with Session(db_engine) as db:
        assert db.get(InterviewSession, sid) is None
        assert db.query(InterviewTurn).filter(InterviewTurn.session_id == sid).count() == 0


def test_get_and_list_interviews_load_turns_in_single_joined_query(client, db_engine):
    s1 = client.post("/interviews", json={"role": "cloud_support"}).json()
    s2 = client.post("/interviews", json={"role": "junior_aws"}).json()

    recorded: list[str] = []

    def on_sql(_conn, _cursor, statement, _params, _context, _executemany):
        sql = " ".join(statement.upper().split())
        if sql.startswith("SELECT"):
            recorded.append(sql)

    event.listen(db_engine, "before_cursor_execute", on_sql)
    try:
        # GET /interviews (all)
        recorded.clear()
        list_resp = client.get("/interviews")
        assert list_resp.status_code == 200
        list_body = list_resp.json()
        assert [s["id"] for s in list_body] == [s1["id"], s2["id"]]
        assert all([t["turn_index"] for t in s["turns"]] == [1, 2, 3] for s in list_body)
        assert len(recorded) == 1
        assert "JOIN INTERVIEW_TURNS" in recorded[0]
        assert "FROM INTERVIEW_TURNS" not in recorded[0]

        # GET /interviews with pagination (must paginate sessions, not joined turn rows)
        recorded.clear()
        page_resp = client.get("/interviews", params={"offset": 1, "limit": 1})
        assert page_resp.status_code == 200
        page_body = page_resp.json()
        assert [s["id"] for s in page_body] == [s2["id"]]
        assert [t["turn_index"] for t in page_body[0]["turns"]] == [1, 2, 3]
        assert len(recorded) == 1
        assert "JOIN INTERVIEW_TURNS" in recorded[0]
        assert "FROM INTERVIEW_TURNS" not in recorded[0]

        # GET /interviews/{session_id}
        recorded.clear()
        get_resp = client.get(f"/interviews/{s1['id']}")
        assert get_resp.status_code == 200
        get_body = get_resp.json()
        assert get_body["id"] == s1["id"]
        assert [t["turn_index"] for t in get_body["turns"]] == [1, 2, 3]
        assert len(recorded) == 1
        assert "JOIN INTERVIEW_TURNS" in recorded[0]
        assert "FROM INTERVIEW_TURNS" not in recorded[0]
    finally:
        event.remove(db_engine, "before_cursor_execute", on_sql)


def test_postgres_concurrent_interview_delete_and_create_races(client, db_engine):
    if db_engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-level locking test")

    # Concurrent answer + delete must serialize cleanly without deadlocking (no 500).
    for _ in range(5):
        session = client.post("/interviews", json={"role": "cloud_support"}).json()
        sid = session["id"]
        t1 = session["turns"][0]

        def answer_req(session_id=sid, turn_id=t1["id"]):
            with TestClient(app, raise_server_exceptions=False) as tc:
                return tc.post(
                    f"/interviews/{session_id}/turns/{turn_id}/answer",
                    json={"answer": "Check logs and health checks."},
                )

        def delete_req(session_id=sid):
            with TestClient(app, raise_server_exceptions=False) as tc:
                return tc.delete(f"/interviews/{session_id}")

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_ans = pool.submit(answer_req)
            f_del = pool.submit(delete_req)
            r_ans, r_del = f_ans.result(timeout=10), f_del.result(timeout=10)

        assert r_del.status_code == 204
        assert r_ans.status_code in (200, 404)
        assert client.get(f"/interviews/{sid}").status_code == 404

    # Concurrent create_interview + delete_source must serialize cleanly (201 or 404, never 500).
    for _ in range(5):
        source_id = create_source(client, label="PG Race JD", status="draft")

        def create_req(src_id=source_id):
            with TestClient(app, raise_server_exceptions=False) as tc:
                return tc.post("/interviews", json={"role": "junior_aws", "source_id": src_id})

        def delete_source_req(src_id=source_id):
            with TestClient(app, raise_server_exceptions=False) as tc:
                return tc.delete(f"/sources/{src_id}")

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_create = pool.submit(create_req)
            f_del_src = pool.submit(delete_source_req)
            r_create, r_del_src = f_create.result(timeout=10), f_del_src.result(timeout=10)

        assert r_del_src.status_code == 204
        assert r_create.status_code in (201, 404)
        if r_create.status_code == 201:
            re_read = client.get(f"/interviews/{r_create.json()['id']}")
            assert re_read.status_code == 200
            assert re_read.json()["source_id"] is None


def test_atomic_conditional_update_rejects_concurrent_duplicate_answer_and_complete(
    client, db_engine
):
    session = client.post("/interviews", json={"role": "cloud_support"}).json()
    sid = session["id"]
    t1, t2, t3 = session["turns"]

    # Simulate a concurrent writer answering turn 1 after the initial read and before the UPDATE.
    class RacingEvaluator:
        def evaluate(self, role, turn_index, turn_type, prompt, answer):
            with Session(db_engine) as peer:
                peer_turn = peer.get(InterviewTurn, t1["id"])
                assert peer_turn is not None
                peer_turn.answer = "First writer answer"
                peer_turn.english_clarity = "First writer clarity"
                peer_turn.technical_accuracy = "First writer accuracy"
                peer_turn.star_structure = "First writer STAR"
                peer_turn.corrected_phrasing = "First writer phrasing"
                peer_turn.uncertainty_note = "First writer note"
                peer_turn.human_review_status = "pending"
                peer.commit()
            return TurnFeedback(
                english_clarity="Second writer clarity",
                technical_accuracy="Second writer accuracy",
                star_structure="Second writer STAR",
                corrected_phrasing="Second writer phrasing",
                uncertainty_note="Second writer note",
            )

    app.dependency_overrides[get_interview_evaluator] = RacingEvaluator
    try:
        resp = client.post(
            f"/interviews/{sid}/turns/{t1['id']}/answer",
            json={"answer": "Second writer answer"},
        )
    finally:
        app.dependency_overrides.pop(get_interview_evaluator, None)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Turn already answered"

    # First writer's answer and feedback must remain intact.
    with Session(db_engine) as db:
        stored_t1 = db.get(InterviewTurn, t1["id"])
        assert stored_t1 is not None
        assert stored_t1.answer == "First writer answer"
        assert stored_t1.english_clarity == "First writer clarity"

    # Answer remaining turns normally.
    for turn in (t2, t3):
        assert (
            client.post(
                f"/interviews/{sid}/turns/{turn['id']}/answer",
                json={"answer": "Detailed answer with logs and verification."},
            ).status_code
            == 200
        )

    # Simulate a concurrent writer completing the session after the initial read.
    first_completed_at = datetime(2026, 7, 3, 9, 0, 0, tzinfo=UTC)
    second_completed_at = datetime(2026, 7, 3, 9, 5, 0, tzinfo=UTC)

    def racing_clock():
        with Session(db_engine) as peer:
            peer_session = peer.get(InterviewSession, sid)
            assert peer_session is not None
            peer_session.status = "completed"
            peer_session.completed_at = first_completed_at
            peer.commit()
        return second_completed_at

    prev_clock = app.dependency_overrides.get(main_module.get_clock)
    app.dependency_overrides[main_module.get_clock] = lambda: racing_clock
    try:
        comp_resp = client.post(f"/interviews/{sid}/complete")
    finally:
        if prev_clock is None:
            app.dependency_overrides.pop(main_module.get_clock, None)
        else:
            app.dependency_overrides[main_module.get_clock] = prev_clock

    assert comp_resp.status_code == 409
    assert comp_resp.json()["detail"] == "Interview session is already completed"

    re_read = client.get(f"/interviews/{sid}").json()
    assert re_read["status"] == "completed"
    assert re_read["completed_at"].startswith("2026-07-03T09:00:00")
