"""Tests for Propuesta 3 static assets, constraints, and real API study workflow."""

from pathlib import Path

import pytest

PROPUESTA3_DIR = Path(__file__).resolve().parents[1] / "app" / "static" / "propuesta3"


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
def test_propuesta3_serves_all_static_modules(client, asset):
    res = client.get(f"/propuesta3/{asset}")
    assert res.status_code == 200
    assert len(res.content) > 0


def test_propuesta3_hides_design_doc_from_http(client):
    assert (PROPUESTA3_DIR / "DESIGN.md").is_file()
    assert client.get("/propuesta3/DESIGN.md").status_code == 404


def test_propuesta3_has_no_external_cdns_and_includes_mobile_meta(client):
    html = client.get("/propuesta3/").text
    assert "viewport-fit=cover" in html
    assert "theme-color" in html
    assert "http://" not in html
    assert "https://" not in html

    css = client.get("/propuesta3/styles.css").text
    assert "100dvh" in css
    assert "prefers-reduced-motion" in css
    assert "@media (hover: hover) and (pointer: fine)" in css
    assert "transition: all" not in css


def test_propuesta3_id_preservation_and_api_flow(client):
    # Verify real API lifecycle used by Propuesta 3 without creating new endpoints.
    deck = client.post(
        "/decks", json={"name": "Cloud interviews", "description": "AWS & Linux"}
    ).json()
    deck_id = deck["id"]

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

    approved = client.post(f"/errors/{err_id}/approve", json={"deck_id": deck_id})
    assert approved.status_code == 201
    assert approved.json()["error"]["status"] == "approved"

    analytics = client.get("/analytics/learning")
    assert analytics.status_code == 200
    summary = analytics.json()
    assert summary["reviews"]["recall"]["denominator"] == 1
    assert summary["error_correction"]["current_approved"] == 1
