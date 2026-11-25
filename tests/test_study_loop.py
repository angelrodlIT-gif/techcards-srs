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


def create_deck(client, name="Study Loop"):
    resp = client.post("/decks", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_study_next_reveal_grade_and_existing_routes(client, set_clock):
    set_clock(datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC))
    did = create_deck(client)
    assert client.get("/study/next", params={"deck_id": did}).status_code == 204
    assert client.get("/study/next", params={"deck_id": 999}).status_code == 404
    assert client.post("/study/999/reveal").status_code == 404
    assert client.post("/study/999/grade", json={"quality": 4}).status_code == 404

    c1 = client.post(
        "/cards",
        json={
            "deck_id": did,
            "front": "What is a VPC?",
            "back": "Virtual Private Cloud",
            "source_label": "AWS Notes",
            "accepted_answers": ["Isolated virtual network"],
            "explanation": "Logical network boundary.",
        },
    ).json()
    c2 = client.post(
        "/cards", json={"deck_id": did, "front": "What is DNS?", "back": "Names"}
    ).json()

    # /decks/{id}/due keeps returning full CardOut; /study/next hides answer fields.
    due = client.get(f"/decks/{did}/due").json()
    assert [c["id"] for c in due] == [c1["id"], c2["id"]] and due[0]["back"] == c1["back"]

    nxt = client.get("/study/next", params={"deck_id": did})
    assert nxt.status_code == 200
    body = nxt.json()
    assert (body["card_id"], body["deck_id"], body["front"], body["source_label"]) == (
        c1["id"],
        did,
        "What is a VPC?",
        "AWS Notes",
    )
    assert (body["repetitions"], body["interval_days"], body["ease_factor"], body["due_date"]) == (
        0,
        0,
        2.5,
        "2026-06-01",
    )
    assert not ({"back", "accepted_answers", "explanation"} & body.keys())

    rev = client.post(f"/study/{c1['id']}/reveal")
    assert rev.status_code == 200
    assert rev.json() == {
        "card_id": c1["id"],
        "deck_id": did,
        "back": "Virtual Private Cloud",
        "accepted_answers": ["Isolated virtual network"],
        "explanation": "Logical network boundary.",
    }

    # Grade updates schedule identically to POST /reviews (reveal not required before grading).
    fields = ("quality", "repetitions", "interval_days", "ease_factor", "due_date")
    g1 = client.post(f"/study/{c1['id']}/grade", json={"quality": 5})
    r2 = client.post("/reviews", json={"card_id": c2["id"], "quality": 5})
    assert (g1.status_code, r2.status_code) == (201, 201)
    assert [g1.json()[k] for k in fields] == [r2.json()[k] for k in fields]
    assert client.get("/study/next", params={"deck_id": did}).status_code == 204

    set_clock(datetime(2026, 6, 2, 12, 0, 0, tzinfo=UTC))
    for q in (4, 3, 2, 1, 0):
        sg = client.post(f"/study/{c1['id']}/grade", json={"quality": q})
        rv = client.post("/reviews", json={"card_id": c2["id"], "quality": q})
        assert (sg.status_code, rv.status_code) == (201, 201)
        assert [sg.json()[k] for k in fields] == [rv.json()[k] for k in fields]

    gen = client.post(
        "/cards/generate", json={"deck_id": did, "text": "AWS Linux Python network", "max_cards": 2}
    )
    assert gen.status_code == 201 and len(gen.json()) == 2


@pytest.mark.parametrize("quality", [-1, 6, True, 2.5, "5"])
def test_study_grade_invalid_quality_rejected(client, quality):
    did = create_deck(client)
    cid = client.post("/cards", json={"deck_id": did, "front": "Q", "back": "A"}).json()["id"]
    assert client.post(f"/study/{cid}/grade", json={"quality": quality}).status_code == 422


def test_study_legacy_null_and_nul_readable(client, db_engine):
    did = create_deck(client)
    is_sqlite = db_engine.dialect.name == "sqlite"
    with Session(db_engine) as session:
        card = Card(
            deck_id=did,
            front="Legacy\x00Front" if is_sqlite else "Legacy Front",
            back="Legacy\x00Back" if is_sqlite else "Legacy Back",
            accepted_answers=None,
            explanation=None,
        )
        session.add(card)
        session.commit()
        cid = card.id
    assert client.get("/study/next", params={"deck_id": did}).json()["card_id"] == cid
    assert client.post(f"/study/{cid}/reveal").json()["accepted_answers"] == []


def test_templates_catalog_and_explicit_instantiate(client, set_clock):
    set_clock(datetime(2026, 6, 1, 9, 0, 0, tzinfo=UTC))
    did = create_deck(client)

    items = client.get("/templates").json()
    assert {"net-vpc", "net-subnetting", "net-dns", "net-tcp-handshake"}.issubset(
        {t["id"] for t in items}
    )
    star_items = [t for t in items if t["category"] == "star"]
    net_items = [t for t in items if t["category"] == "networking"]
    assert len(star_items) >= 2 and len(net_items) == 4
    for t in star_items:
        assert t["kind"] == "behavioral"
        text = f"{t['front']} {t['back']}".lower()
        assert "real experience" in text and "invent" in text
    for t in net_items:
        assert t["kind"] == "interview_phrase" and len(t["follow_up_questions"]) >= 2

    assert client.get("/templates/net-vpc").json()["id"] == "net-vpc"
    assert client.get("/templates/unknown").status_code == 404
    assert client.get("/cards").json() == []  # list/get never insert cards

    assert client.post("/templates/unknown/cards", json={"deck_id": did}).status_code == 404
    assert client.post("/templates/net-vpc/cards", json={"deck_id": 999}).status_code == 404

    created = client.post("/templates/net-vpc/cards", json={"deck_id": did})
    assert created.status_code == 201
    card = created.json()
    assert (card["deck_id"], card["kind"], card["source_label"], card["due_date"]) == (
        did,
        "interview_phrase",
        "template:net-vpc",
        "2026-06-01",
    )
    assert len(client.get("/cards").json()) == 1


def test_errors_crud_lifecycle_validation_and_links(client, set_clock):
    set_clock(datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC))
    did = create_deck(client)
    assert client.get("/errors").json() == []

    for bad in (
        {"attempted": "   ", "corrected": "Ok", "rationale": "Why"},
        {"attempted": "A", "corrected": "  ", "rationale": "Why"},
        {"attempted": "A", "corrected": "B", "rationale": "\t"},
        {"attempted": "A\x00B", "corrected": "B", "rationale": "Why"},
        {"attempted": "A", "corrected": "B\x00C", "rationale": "Why"},
        {"attempted": "A", "corrected": "B", "rationale": "Why\x00"},
        {"attempted": "x" * 5001, "corrected": "B", "rationale": "Why"},
    ):
        assert client.post("/errors", json=bad).status_code == 422

    assert client.get("/errors/999").status_code == 404
    assert client.delete("/errors/999").status_code == 404
    assert (
        client.put(
            "/errors/999", json={"attempted": "A", "corrected": "B", "rationale": "C"}
        ).status_code
        == 404
    )
    assert client.post("/errors/999/discard").status_code == 404
    assert client.post("/errors/999/approve", json={"deck_id": did}).status_code == 404

    e1 = client.post(
        "/errors",
        json={
            "attempted": "  The service did not responded  ",
            "corrected": "  The service did not respond  ",
            "rationale": "  Use base verb after 'did not'.  ",
        },
    ).json()
    assert e1 == {
        "id": e1["id"],
        "attempted": "The service did not responded",
        "corrected": "The service did not respond",
        "rationale": "Use base verb after 'did not'.",
        "status": "draft",
        "card_id": None,
    }
    e2 = client.post(
        "/errors",
        json={"attempted": "I am agree", "corrected": "I agree", "rationale": "Agree is a verb."},
    ).json()

    edited = client.put(
        f"/errors/{e1['id']}",
        json={
            "attempted": "The server did not responded",
            "corrected": "The server did not respond",
            "rationale": "After 'did not', use base verb.",
        },
    )
    assert (
        edited.status_code == 200 and edited.json()["attempted"] == "The server did not responded"
    )

    # Discard draft -> terminal 409, creates no card.
    assert client.post(f"/errors/{e2['id']}/discard").json()["status"] == "discarded"
    assert client.get("/cards").json() == []
    assert (
        client.put(
            f"/errors/{e2['id']}", json={"attempted": "X", "corrected": "Y", "rationale": "Z"}
        ).status_code
        == 409
    )
    assert client.post(f"/errors/{e2['id']}/discard").status_code == 409
    assert client.post(f"/errors/{e2['id']}/approve", json={"deck_id": did}).status_code == 409

    # Approve errors leave row in draft.
    assert client.post(f"/errors/{e1['id']}/approve", json={"deck_id": 999}).status_code == 404
    for bad_approve in (
        {"deck_id": did, "kind": "cloze"},
        {"deck_id": did, "front": "Bad\x00front"},
    ):
        assert client.post(f"/errors/{e1['id']}/approve", json=bad_approve).status_code == 422
    assert client.get(f"/errors/{e1['id']}").json()["status"] == "draft"

    approved = client.post(f"/errors/{e1['id']}/approve", json={"deck_id": did})
    assert approved.status_code == 201
    err_out, card_out = approved.json()["error"], approved.json()["card"]
    assert (err_out["status"], err_out["card_id"], card_out["error_id"]) == (
        "approved",
        card_out["id"],
        err_out["id"],
    )
    assert (card_out["front"], card_out["back"], card_out["explanation"]) == (
        "Correct: The server did not responded",
        "The server did not respond",
        "After 'did not', use base verb.",
    )
    assert client.get(f"/cards/{card_out['id']}").json()["error_id"] == err_out["id"]
    # PUT /cards preserves error_id.
    upd = client.put(
        f"/cards/{card_out['id']}", json={"deck_id": did, "front": "Edited", "back": "Fixed"}
    )
    assert upd.status_code == 200 and upd.json()["error_id"] == err_out["id"]
    assert client.post(f"/errors/{e1['id']}/approve", json={"deck_id": did}).status_code == 409

    # Filter and pagination.
    assert [e["id"] for e in client.get("/errors", params={"status": "approved"}).json()] == [
        e1["id"]
    ]
    assert [e["id"] for e in client.get("/errors", params={"status": "discarded"}).json()] == [
        e2["id"]
    ]
    assert len(client.get("/errors", params={"offset": 1, "limit": 1}).json()) == 1

    # Delete approved error -> card stays intact; delete card / deck -> error card_id clears.
    assert client.delete(f"/errors/{e1['id']}").status_code == 204
    assert client.get(f"/cards/{card_out['id']}").json()["error_id"] is None

    e3 = client.post(
        "/errors", json={"attempted": "depend of", "corrected": "depend on", "rationale": "Use on."}
    ).json()
    c3 = client.post(
        f"/errors/{e3['id']}/approve",
        json={"deck_id": did, "front": "Results depend ____ load.", "back": "on", "kind": "cloze"},
    ).json()["card"]
    assert client.delete(f"/cards/{c3['id']}").status_code == 204
    assert client.get(f"/errors/{e3['id']}").json()["card_id"] is None

    e4 = client.post(
        "/errors", json={"attempted": "in Monday", "corrected": "on Monday", "rationale": "Days."}
    ).json()
    assert client.post(f"/errors/{e4['id']}/approve", json={"deck_id": did}).status_code == 201
    assert client.delete(f"/decks/{did}").status_code == 204
    assert client.get(f"/errors/{e4['id']}").json()["card_id"] is None


def test_error_approve_derived_front_length_boundaries(client):
    did = create_deck(client, name="Boundary Deck")

    # 4,992-char and 5,000-char attempted -> derived "Correct: ..." exceeds 5,000 chars -> 422.
    for length in (4992, 5000):
        err = client.post(
            "/errors",
            json={"attempted": "a" * length, "corrected": "Fixed", "rationale": "Why"},
        ).json()
        assert client.post(f"/errors/{err['id']}/approve", json={"deck_id": did}).status_code == 422
        assert client.get(f"/errors/{err['id']}").json()["status"] == "draft"
    assert client.get("/cards").json() == []

    # Valid short override on a 5,000-char error still succeeds and remains PUT-editable.
    overridden = client.post(
        f"/errors/{err['id']}/approve",
        json={"deck_id": did, "front": "Short override prompt"},
    )
    assert overridden.status_code == 201
    c_ov = overridden.json()["card"]
    assert c_ov["front"] == "Short override prompt" and c_ov["error_id"] == err["id"]
    assert (
        client.put(
            f"/cards/{c_ov['id']}",
            json={"deck_id": did, "front": c_ov["front"], "back": "Updated back"},
        ).status_code
        == 200
    )

    # 4,991-char attempted -> derived front is exactly 5,000 chars -> 201 and PUT-editable.
    fit_err = client.post(
        "/errors",
        json={"attempted": "b" * 4991, "corrected": "Fixed", "rationale": "Why"},
    ).json()
    fitted = client.post(f"/errors/{fit_err['id']}/approve", json={"deck_id": did})
    assert fitted.status_code == 201
    c_fit = fitted.json()["card"]
    assert len(c_fit["front"]) == 5000 and c_fit["error_id"] == fit_err["id"]
    assert (
        client.put(
            f"/cards/{c_fit['id']}",
            json={"deck_id": did, "front": c_fit["front"], "back": "Unrelated edit"},
        ).status_code
        == 200
    )


def test_error_logs_migration_round_trip(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / 'errors_migration.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()

    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "migrations"))
    engine = create_engine(db_url)
    try:
        command.upgrade(cfg, "0004")
        assert "error_logs" not in inspect(engine).get_table_names()
        with engine.begin() as conn:
            conn.execute(sa_text("INSERT INTO decks (id, name, description) VALUES (1, 'D', '')"))
            conn.execute(
                sa_text(
                    "INSERT INTO cards (id, deck_id, front, back, kind, source_label, "
                    "repetitions, interval_days, ease_factor, due_date) "
                    "VALUES (1, 1, 'Q', 'A', 'vocabulary', 'M1', 2, 6, 2.6, '2026-06-10')"
                )
            )
        command.upgrade(cfg, "head")
        assert "error_logs" in inspect(engine).get_table_names()
        assert inspect(engine).get_indexes("error_logs")[0]["unique"]
        with engine.connect() as conn:
            assert conn.execute(sa_text("SELECT COUNT(*) FROM error_logs")).scalar_one() == 0

        command.downgrade(cfg, "0004")
        assert "error_logs" not in inspect(engine).get_table_names()
        with engine.connect() as conn:
            row = conn.execute(
                sa_text(
                    "SELECT front, back, repetitions, interval_days, ease_factor, due_date "
                    "FROM cards WHERE id = 1"
                )
            ).one()
            assert tuple(row) == ("Q", "A", 2, 6, 2.6, "2026-06-10")

        command.upgrade(cfg, "head")
        assert "error_logs" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
        monkeypatch.undo()
        get_settings.cache_clear()


def test_error_suggest_validation_and_boundaries(client):
    did = create_deck(client, name="Remediation Validation")

    bad_payloads = [
        {"answer": "I am agree"},
        *({"answer": "I am agree", "consent": v} for v in (False, 1, "true", None)),
        *(
            {"answer": "Ok", "consent": True, k: "bad\x00v"}
            for k in ("answer", "prompt", "corrected", "rationale")
        ),
        {"answer": "a" * 4992, "corrected": "Fixed", "consent": True},
        {"prompt": "Q" * 100, "answer": "a" * 4900, "corrected": "Fixed", "consent": True},
        {"answer": "a" * 4980, "category": "technical", "consent": True},
        {"answer": "a" * 4950, "category": "star", "consent": True},
        {"answer": "Short", "category": "star", "rationale": "r" * 4990, "consent": True},
    ]
    for bad in bad_payloads:
        assert client.post("/errors/suggest", json=bad).status_code == 422
    assert (
        "consent"
        in client.post("/errors/suggest", json={"answer": "Ok", "consent": False}).text.lower()
    )

    ok = client.post(
        "/errors/suggest", json={"answer": "b" * 4991, "corrected": "Fixed", "consent": True}
    )
    assert ok.status_code == 201 and len(ok.json()["suggested_card"]["front"]) == 5000
    assert client.get("/cards").json() == []
    approved = client.post(f"/errors/{ok.json()['error']['id']}/approve", json={"deck_id": did})
    assert approved.status_code == 201 and len(approved.json()["card"]["front"]) == 5000


def test_remediation_loop_suggest_approve_study_export_and_delete(client, set_clock):
    set_clock(datetime(2026, 7, 1, 10, 0, 0, tzinfo=UTC))
    did = create_deck(client, name="Interview Prep")
    plain = client.post(
        "/cards", json={"deck_id": did, "front": "Plain", "back": "Back", "kind": "behavioral"}
    ).json()

    def suggest(**kw):
        resp = client.post("/errors/suggest", json={"consent": True, **kw})
        assert resp.status_code == 201
        return resp.json()

    def study_next(**params):
        return client.get("/study/next", params={"deck_id": did, **params})

    # 1. Technical suggestions: prompt + phrasing fixes, plus clean fallback.
    tech = suggest(
        prompt="Explain API latency",
        answer="The service did not responded in monday and depends of cache.",
    )
    t_err, t_card = tech["error"], tech["suggested_card"]
    assert t_err["status"] == "draft" and t_err["card_id"] is None
    assert t_err["attempted"] == (
        "Prompt: Explain API latency\n"
        "Answer: The service did not responded in monday and depends of cache."
    )
    assert t_err["corrected"] == "The service did not respond on Monday and depends on cache."
    assert t_err["rationale"].startswith("[Technical remediation] ")
    assert t_card == {
        "front": f"Correct: {t_err['attempted']}",
        "back": t_err["corrected"],
        "kind": "interview_phrase",
        "explanation": t_err["rationale"],
    }
    tech_clean = suggest(answer="DNS resolves hostnames to IPs.")
    assert tech_clean["error"]["corrected"] == (
        "Refined technical explanation: DNS resolves hostnames to IPs."
    )

    # 2. STAR suggestions: missing markers, full markers, custom rationale prefixing.
    star = suggest(
        answer="I am agree we fixed the outage, though it didn't responded at first.",
        category="star",
    )
    s_err, s_card = star["error"], star["suggested_card"]
    assert s_card["kind"] == "behavioral" and "real experiences only" in s_err["corrected"].lower()
    assert "I agree" in s_err["corrected"] and "didn't respond" in s_err["corrected"]
    assert (
        s_err["rationale"].startswith("[STAR remediation] ") and "Situation" in s_err["rationale"]
    )
    star_full = suggest(
        answer="Situation: outage. Task: fix. Action: rollback. Result: restored.", category="star"
    )
    assert "All STAR elements" in star_full["error"]["rationale"]
    star_custom = suggest(answer="Outage fix.", category="star", rationale="Add metrics.")
    assert star_custom["error"]["rationale"] == "[STAR remediation] Add metrics."
    assert len(client.get("/cards").json()) == 1  # suggest never creates cards

    # 3. Approve STAR (defaults to behavioral), technical (interview_phrase), and explicit override.
    s_app = client.post(f"/errors/{s_err['id']}/approve", json={"deck_id": did}).json()
    t_app = client.post(f"/errors/{t_err['id']}/approve", json={"deck_id": did}).json()
    ov = client.post(
        f"/errors/{star_custom['error']['id']}/approve",
        json={"deck_id": did, "kind": "interview_phrase"},
    ).json()
    assert (s_app["card"]["kind"], t_app["card"]["kind"], ov["card"]["kind"]) == (
        "behavioral",
        "interview_phrase",
        "interview_phrase",
    )

    # 4. Practice across sessions using /study/next filters (kind & remediation_only).
    p0 = study_next(kind="behavioral").json()
    assert p0["card_id"] == plain["id"] and p0["error_id"] is None

    s_p = study_next(remediation_only=True, kind="behavioral").json()
    assert s_p["card_id"] == s_app["card"]["id"] and s_p["error_id"] == s_err["id"]
    assert not ({"back", "accepted_answers", "explanation"} & s_p.keys())
    assert client.post(f"/study/{s_p['card_id']}/reveal").json()["back"] == s_err["corrected"]
    assert client.post(f"/study/{s_p['card_id']}/grade", json={"quality": 4}).status_code == 201
    assert study_next(remediation_only=True, kind="behavioral").status_code == 204

    t_p = study_next(remediation_only=True, kind="interview_phrase").json()
    assert t_p["card_id"] == t_app["card"]["id"] and t_p["error_id"] == t_err["id"]
    assert client.post(f"/study/{t_p['card_id']}/grade", json={"quality": 4}).status_code == 201

    set_clock(datetime(2026, 7, 2, 10, 0, 0, tzinfo=UTC))
    s2 = study_next(remediation_only=True, kind="behavioral").json()
    assert s2["card_id"] == s_app["card"]["id"] and s2["repetitions"] == 1
    g2 = client.post(f"/study/{s2['card_id']}/grade", json={"quality": 5}).json()
    assert (g2["repetitions"], g2["interval_days"]) == (2, 6)

    # 5. Export preserves original answers, linked card snapshots, filters, and pagination.
    exp = client.get(
        "/errors/export", params={"status": "approved", "offset": 0, "limit": 2}
    ).json()
    assert exp["exported_at"] == "2026-07-02T10:00:00Z" and exp["count"] == 2
    assert [i["id"] for i in exp["items"]] == [t_err["id"], s_err["id"]]
    assert exp["items"][0]["attempted"] == t_err["attempted"]
    assert (exp["items"][1]["card"]["repetitions"], exp["items"][1]["card"]["interval_days"]) == (
        2,
        6,
    )
    draft_exp = client.get("/errors/export", params={"status": "draft"}).json()
    assert draft_exp["count"] == 2 and all(i["card"] is None for i in draft_exp["items"])

    # 6. Deletion: default keeps card (error_id=None); delete_card=true deletes both atomically.
    assert client.delete(f"/errors/{t_err['id']}").status_code == 204
    assert client.get(f"/cards/{t_app['card']['id']}").json()["error_id"] is None
    assert client.delete(f"/errors/{s_err['id']}", params={"delete_card": True}).status_code == 204
    assert client.get(f"/errors/{s_err['id']}").status_code == 404
    assert client.get(f"/cards/{s_app['card']['id']}").status_code == 404
    eid = tech_clean["error"]["id"]
    assert client.delete(f"/errors/{eid}", params={"delete_card": True}).status_code == 204
    assert client.delete("/errors/9999", params={"delete_card": True}).status_code == 404
