from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.main as main_module
from app.config import get_settings
from app.models import Source


def create_deck(client, name="Cloud English"):
    resp = client.post("/decks", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_source_intake_normalization_and_duplicates(client):
    assert client.get("/sources").json() == []

    # URL-less sources (omitted or blank) are allowed as duplicates, even with the same label.
    no_url = client.post("/sources", json={"label": "  AWS Notes  ", "excerpt": "  IAM basics  "})
    assert no_url.status_code == 201
    assert no_url.json() == {
        "id": no_url.json()["id"],
        "label": "AWS Notes",
        "url": None,
        "normalized_url": None,
        "excerpt": "IAM basics",
        "status": "draft",
    }
    blank = client.post("/sources", json={"label": "AWS Notes", "url": " \t ", "excerpt": "  "})
    assert blank.status_code == 201
    assert (blank.json()["url"], blank.json()["normalized_url"], blank.json()["excerpt"]) == (
        None,
        None,
        None,
    )

    first = client.post(
        "/sources",
        json={
            "label": "AWS IAM Guide",
            "url": "  HTTPS://Docs.AWS.Amazon.com:443/IAM/Guide/?a=1#intro  ",
            "excerpt": "Use least privilege.",
        },
    )
    assert first.status_code == 201
    assert first.json()["url"] == "HTTPS://Docs.AWS.Amazon.com:443/IAM/Guide/?a=1#intro"
    assert first.json()["normalized_url"] == "https://docs.aws.amazon.com/IAM/Guide?a=1"

    for dup_url in [
        "https://docs.aws.amazon.com/IAM/Guide?a=1",
        "https://DOCS.aws.amazon.com/IAM/Guide/?a=1#other",
        "https://docs.aws.amazon.com:443/IAM/Guide?a=1",
    ]:
        assert client.post("/sources", json={"label": "Dup", "url": dup_url}).status_code == 409

    root = client.post("/sources", json={"label": "Root", "url": "http://Example.com:80"})
    assert root.status_code == 201 and root.json()["normalized_url"] == "http://example.com/"
    assert (
        client.post("/sources", json={"label": "R2", "url": "HTTP://example.com/#x"}).status_code
        == 409
    )

    for distinct_url in [
        "https://www.docs.aws.amazon.com/IAM/Guide?a=1",
        "https://docs.aws.amazon.com/IAM/Guide?a=2",
        "https://docs.aws.amazon.com/iam/guide?a=1",
        "https://docs.aws.amazon.com:8443/IAM/Guide?a=1",
    ]:
        assert (
            client.post("/sources", json={"label": "Distinct", "url": distinct_url}).status_code
            == 201
        )


@pytest.mark.parametrize(
    "bad_url",
    [
        "/relative/path",
        "example.com/no-scheme",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "https://",
        "https://example.com/has space",
        "https://example.com:99999/bad-port",
        "https://user:pass@example.com/secret",
        123,
    ],
)
def test_source_invalid_url_rejected(client, bad_url):
    assert client.post("/sources", json={"label": "Bad", "url": bad_url}).status_code == 422


def test_source_validation_and_missing_resources(client):
    assert client.post("/sources", json={"label": "   "}).status_code == 422
    assert client.post("/sources", json={"label": "x" * 256}).status_code == 422
    assert client.get("/sources/999").status_code == 404
    assert client.put("/sources/999", json={"label": "X"}).status_code == 404
    assert client.delete("/sources/999").status_code == 404
    assert client.post("/sources/999/discard").status_code == 404
    assert (
        client.post(
            "/sources/999/approve", json={"deck_id": 1, "front": "Q", "back": "A"}
        ).status_code
        == 404
    )


def test_source_edit_discard_approve_and_delete_lifecycle(client, set_clock):
    set_clock(datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC))
    did = create_deck(client)

    # Advance an existing card's SM-2 schedule to verify approve leaves it untouched.
    existing_id = client.post(
        "/cards", json={"deck_id": did, "front": "VPC?", "back": "Network"}
    ).json()["id"]
    assert client.post("/reviews", json={"card_id": existing_id, "quality": 5}).status_code == 201
    existing_before = client.get(f"/cards/{existing_id}").json()

    s1 = client.post(
        "/sources",
        json={"label": "AWS JD", "url": "https://example.com/jd/1/", "excerpt": "Original"},
    ).json()
    s2 = client.post("/sources", json={"label": "Blog", "url": "https://example.com/blog/2"}).json()

    # Edit draft: replaces fields (no merge), keeps own URL, rejects colliding URL with 409.
    edited = client.put(
        f"/sources/{s1['id']}",
        json={
            "label": "AWS JD v2",
            "url": "https://EXAMPLE.COM/jd/1#details",
            "excerpt": "Replaced excerpt",
        },
    )
    assert edited.status_code == 200
    assert (edited.json()["label"], edited.json()["excerpt"], edited.json()["normalized_url"]) == (
        "AWS JD v2",
        "Replaced excerpt",
        "https://example.com/jd/1",
    )
    assert (
        client.put(
            f"/sources/{s1['id']}", json={"label": "Dup", "url": "https://example.com/blog/2/"}
        ).status_code
        == 409
    )

    # Discard draft: creates no card and is terminal.
    cards_before = len(client.get("/cards").json())
    assert client.post(f"/sources/{s2['id']}/discard").json()["status"] == "discarded"
    assert len(client.get("/cards").json()) == cards_before
    assert client.put(f"/sources/{s2['id']}", json={"label": "No"}).status_code == 409
    assert client.post(f"/sources/{s2['id']}/discard").status_code == 409
    assert (
        client.post(
            f"/sources/{s2['id']}/approve", json={"deck_id": did, "front": "Q", "back": "A"}
        ).status_code
        == 409
    )

    # Approve errors: missing fields -> 422; nonexistent deck -> 404 (source stays draft).
    assert client.post(f"/sources/{s1['id']}/approve", json={"front": "Q"}).status_code == 422
    assert (
        client.post(
            f"/sources/{s1['id']}/approve", json={"deck_id": 999, "front": "Q", "back": "A"}
        ).status_code
        == 404
    )
    assert client.get(f"/sources/{s1['id']}").json()["status"] == "draft"

    # Approve draft -> creates card with source_label and default SM-2 schedule.
    approved = client.post(
        f"/sources/{s1['id']}/approve",
        json={"deck_id": did, "front": "IAM access denied?", "back": "Check IAM/SCP policies."},
    )
    assert approved.status_code == 201
    card = approved.json()["card"]
    assert approved.json()["source"]["status"] == "approved"
    assert (card["deck_id"], card["source_label"], card["kind"]) == (did, "AWS JD v2", "vocabulary")
    assert (card["repetitions"], card["interval_days"], card["ease_factor"], card["due_date"]) == (
        0,
        0,
        2.5,
        "2026-05-01",
    )
    assert client.get(f"/cards/{existing_id}").json() == existing_before
    assert [c["id"] for c in client.get(f"/decks/{did}/due").json()] == [card["id"]]

    # Approved source rejects edit/approve/discard with 409.
    assert client.put(f"/sources/{s1['id']}", json={"label": "No"}).status_code == 409
    assert client.post(f"/sources/{s1['id']}/discard").status_code == 409
    assert (
        client.post(
            f"/sources/{s1['id']}/approve", json={"deck_id": did, "front": "Q", "back": "A"}
        ).status_code
        == 409
    )
    assert [s["id"] for s in client.get("/sources", params={"status": "approved"}).json()] == [
        s1["id"]
    ]

    # Delete source in approved/discarded status -> 204, leaves card intact, frees URL.
    assert client.delete(f"/sources/{s1['id']}").status_code == 204
    assert client.get(f"/sources/{s1['id']}").status_code == 404
    assert client.get(f"/cards/{card['id']}").json()["source_label"] == "AWS JD v2"
    assert (
        client.post(
            "/sources", json={"label": "Again", "url": "https://example.com/jd/1"}
        ).status_code
        == 201
    )
    # Delete discarded source also returns 204.
    assert client.delete(f"/sources/{s2['id']}").status_code == 204


def test_source_concurrent_duplicate_url_integrity_error_returns_409(
    client, db_engine, monkeypatch
):
    # Create a URL-less draft first (previous persisted normalized_url is NULL).
    draft = client.post("/sources", json={"label": "URL-less Draft"}).json()
    assert draft["normalized_url"] is None

    original_check = main_module.ensure_unique_source_url

    def claim_url_after_precheck(db, normalized_url, exclude_id=None):
        original_check(db, normalized_url, exclude_id=exclude_id)
        if normalized_url is not None:
            with Session(db_engine) as peer:
                peer.add(
                    Source(
                        label="Peer Claim",
                        url=normalized_url,
                        normalized_url=normalized_url,
                        status="draft",
                    )
                )
                peer.commit()

    monkeypatch.setattr(main_module, "ensure_unique_source_url", claim_url_after_precheck)

    # PUT from NULL -> raced URL hits unique index; rollback expires draft, still returns 409.
    put_resp = client.put(
        f"/sources/{draft['id']}",
        json={"label": "Updated", "url": "https://example.com/raced-put/"},
    )
    assert put_resp.status_code == 409
    reloaded = client.get(f"/sources/{draft['id']}").json()
    assert reloaded["label"] == "URL-less Draft"
    assert reloaded["url"] is None
    assert reloaded["normalized_url"] is None

    # POST racing after precheck also maps the DB unique index violation to 409.
    post_resp = client.post(
        "/sources",
        json={"label": "Raced Create", "url": "https://example.com/raced-post/"},
    )
    assert post_resp.status_code == 409


def test_sources_migration_round_trip(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / 'sources_migration.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()

    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "migrations"))
    engine = create_engine(db_url)
    try:
        command.upgrade(cfg, "0002")
        assert "sources" not in inspect(engine).get_table_names()
        with engine.begin() as conn:
            conn.execute(sa_text("INSERT INTO decks (id, name, description) VALUES (1, 'D', '')"))
            conn.execute(
                sa_text(
                    "INSERT INTO cards (id, deck_id, front, back, kind, source_label, "
                    "repetitions, interval_days, ease_factor, due_date) "
                    "VALUES (1, 1, 'Q', 'A', 'vocabulary', 'M1', 1, 1, 2.6, '2026-05-02')"
                )
            )

        command.upgrade(cfg, "head")
        assert "sources" in inspect(engine).get_table_names()
        indexes = {idx["name"]: idx for idx in inspect(engine).get_indexes("sources")}
        assert indexes["uq_sources_normalized_url"]["unique"]

        with engine.begin() as conn:
            conn.execute(
                sa_text("INSERT INTO sources (label, status) VALUES ('A', 'draft'), ('A', 'draft')")
            )
            conn.execute(
                sa_text(
                    "INSERT INTO sources (label, url, normalized_url, status) "
                    "VALUES ('B', 'https://example.com/', 'https://example.com/', 'draft')"
                )
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    sa_text(
                        "INSERT INTO sources (label, url, normalized_url, status) "
                        "VALUES ('C', 'https://example.com/', 'https://example.com/', 'draft')"
                    )
                )

        command.downgrade(cfg, "0002")
        assert "sources" not in inspect(engine).get_table_names()
        with engine.connect() as conn:
            row = conn.execute(
                sa_text(
                    "SELECT source_label, repetitions, interval_days, ease_factor, due_date "
                    "FROM cards WHERE id = 1"
                )
            ).one()
            assert tuple(row) == ("M1", 1, 1, 2.6, "2026-05-02")

        command.upgrade(cfg, "head")
        assert "sources" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
        monkeypatch.undo()
        get_settings.cache_clear()
