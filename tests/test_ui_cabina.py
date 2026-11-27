"""Tests for the main Cabina UI routes, static assets, security, and API study flow."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = REPO_ROOT / "app" / "static" / "ui"


@pytest.mark.parametrize("path", ["/ui", "/propuesta3", "/propuesta3/"])
def test_ui_and_legacy_alias_redirect_to_ui_slash(client, path):
    res = client.get(path, follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/ui/"


@pytest.mark.parametrize(
    "asset",
    [
        "index.html",
        "styles.css",
        "app.js",
        "api.js",
        "format.js",
        "fixtures.js",
        "components.js",
        "views.js",
    ],
)
def test_ui_serves_all_static_modules(client, asset):
    res = client.get(f"/ui/{asset}")
    assert res.status_code == 200
    assert len(res.content) > 0


def test_ui_index_uses_relative_assets_and_techcards_branding(client):
    res = client.get("/ui/")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")

    html = res.text
    assert 'href="styles.css"' in html
    assert 'src="app.js"' in html
    assert "TechCards" in html
    assert "Propuesta 3" not in html
    assert "/propuestas" not in html


def test_ui_routes_are_excluded_from_openapi_schema(client):
    paths = client.get("/openapi.json").json()["paths"]
    for hidden_path in ("/ui", "/ui/{asset_path}", "/propuesta3", "/propuesta3/"):
        assert hidden_path not in paths


def test_design_doc_moved_to_docs_and_not_served(client):
    assert not (UI_DIR / "DESIGN.md").exists()
    assert (REPO_ROOT / "docs" / "UI_CABINA.md").is_file()
    assert client.get("/ui/DESIGN.md").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/ui/missing.js",
        "/ui/DESIGN.md",
        "/ui/../ui.py",
        "/ui/%2e%2e/ui.py",
        "/ui/%2e%2e/%2e%2e/pyproject.toml",
        "/ui/..%2f..%2fpyproject.toml",
        "/ui/index.html%00.js",
        "/ui//etc/passwd",
        "/propuestas",
        "/propuesta1",
        "/propuesta2",
        "/propuesta3/styles.css",
    ],
)
def test_ui_rejects_traversal_and_unknown_paths(client, path):
    assert client.get(path, follow_redirects=False).status_code == 404


def test_ui_has_no_external_cdns_and_preserves_mobile_and_id_safeguards(client):
    html = client.get("/ui/").text
    assert "viewport-fit=cover" in html
    assert "theme-color" in html
    assert "http://" not in html
    assert "https://" not in html

    css = client.get("/ui/styles.css").text
    assert "100dvh" in css
    assert "prefers-reduced-motion" in css
    assert "@media (hover: hover) and (pointer: fine)" in css
    assert "transition: all" not in css

    api_js = client.get("/ui/api.js").text
    assert "quoteLargeIdFields" in api_js
    assert "parseJsonPreservingIds" in api_js
    for client_fn in ("updateDeck", "updateCard", "updateSource", "updateError", "studyAudio"):
        assert client_fn in api_js

    app_js = client.get("/ui/app.js").text
    for handler in (
        "openEditDeckModal",
        "openEditCardModal",
        "openEditSourceModal",
        "openEditErrorModal",
    ):
        assert handler in app_js

    fixtures_js = client.get("/ui/fixtures.js").text
    assert "9007199254740993123" in fixtures_js


def test_ui_real_api_study_workflow(client):
    # Verify real API lifecycle used by the cockpit UI without adding new API endpoints.
    deck = client.post(
        "/decks", json={"name": "Cloud interviews", "description": "AWS & Linux"}
    ).json()
    deck_id = deck["id"]

    updated_deck = client.put(
        f"/decks/{deck_id}",
        json={"name": "Cloud interviews (updated)", "description": "AWS, Linux & SQL"},
    )
    assert updated_deck.status_code == 200
    assert updated_deck.json()["name"] == "Cloud interviews (updated)"

    generated = client.post(
        "/cards/generate",
        json={
            "deck_id": deck_id,
            "text": "AWS networking, Docker containers, and PostgreSQL transactions in production.",
            "max_cards": 3,
        },
    )
    assert generated.status_code == 201
    cards = generated.json()
    assert len(cards) == 3

    # Edit card while preserving SRS schedule
    edited_card = client.put(
        f"/cards/{cards[0]['id']}",
        json={
            "deck_id": deck_id,
            "front": f"{cards[0]['front']} (edited)",
            "back": cards[0]["back"],
            "kind": cards[0]["kind"],
            "accepted_answers": ["variant answer"],
            "explanation": "clarification",
        },
    )
    assert edited_card.status_code == 200
    assert edited_card.json()["front"].endswith("(edited)")

    # Listening card returns honest 503 when Polly is disabled by default
    listening_card = client.post(
        "/cards",
        json={
            "deck_id": deck_id,
            "front": "Listen to the incident summary.",
            "back": "The load balancer returned 503 after the target group failed health checks.",
            "kind": "listening",
        },
    )
    assert listening_card.status_code == 201
    listening_id = listening_card.json()["id"]
    audio_res = client.post(
        f"/study/{listening_id}/audio",
        headers={"Polly-Opt-In": "true", "Host": "127.0.0.1"},
    )
    assert audio_res.status_code == 503

    # Delete a card
    assert client.delete(f"/cards/{listening_id}").status_code == 204

    tpl_card = client.post("/templates/net-vpc/cards", json={"deck_id": deck_id})
    assert tpl_card.status_code == 201

    due = client.get(f"/decks/{deck_id}/due")
    assert due.status_code == 200
    assert len(due.json()) == 4

    next_card = client.get("/study/next", params={"deck_id": deck_id})
    assert next_card.status_code == 200
    card_id = next_card.json()["card_id"]

    reveal = client.post(f"/study/{card_id}/reveal")
    assert reveal.status_code == 200
    assert "back" in reveal.json()

    grade = client.post(f"/study/{card_id}/grade", json={"quality": 4})
    assert grade.status_code == 201

    # Sources: create, edit draft, approve, discard, delete
    source = client.post(
        "/sources",
        json={
            "label": "AWS VPC guide",
            "url": "https://example.org/aws-vpc",
            "excerpt": "Route tables control subnet traffic.",
        },
    )
    assert source.status_code == 201
    src_id = source.json()["id"]
    edited_source = client.put(
        f"/sources/{src_id}",
        json={
            "label": "AWS VPC guide (v2)",
            "url": "https://example.org/aws-vpc",
            "excerpt": "Updated route table excerpt.",
        },
    )
    assert edited_source.status_code == 200
    assert edited_source.json()["label"] == "AWS VPC guide (v2)"
    approved_source = client.post(
        f"/sources/{src_id}/approve",
        json={
            "deck_id": deck_id,
            "front": "What controls subnet traffic in AWS VPC?",
            "back": "Route tables control where network traffic is directed.",
            "kind": "interview_phrase",
        },
    )
    assert approved_source.status_code == 201
    assert approved_source.json()["source"]["status"] == "approved"

    # Errors: suggest, edit draft, approve, export
    suggestion = client.post(
        "/errors/suggest",
        json={
            "category": "technical",
            "answer": "The service did not responded in Monday.",
            "consent": True,
        },
    )
    assert suggestion.status_code == 201
    err_id = suggestion.json()["error"]["id"]

    edited_err = client.put(
        f"/errors/{err_id}",
        json={
            "attempted": "The service did not responded in Monday.",
            "corrected": "The service did not respond on Monday.",
            "rationale": "Use base verb after 'did not' and 'on' with days of the week.",
        },
    )
    assert edited_err.status_code == 200
    assert edited_err.json()["corrected"] == "The service did not respond on Monday."

    approved = client.post(f"/errors/{err_id}/approve", json={"deck_id": deck_id})
    assert approved.status_code == 201
    assert approved.json()["error"]["status"] == "approved"

    exported = client.get("/errors/export")
    assert exported.status_code == 200
    assert exported.json()["count"] == 1

    analytics = client.get("/analytics/learning")
    assert analytics.status_code == 200
    summary = analytics.json()
    assert summary["reviews"]["recall"]["denominator"] == 1
    assert summary["error_correction"]["current_approved"] == 1

    # Delete deck cleans up cleanly
    assert client.delete(f"/decks/{deck_id}").status_code == 204
