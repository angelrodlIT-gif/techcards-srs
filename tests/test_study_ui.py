def test_ui_serves_html_static_js_and_root_redirects(client):
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 302
    assert root.headers["location"] == "/ui"

    page = client.get("/ui")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    html = page.text
    for expected in (
        "TechCards SRS",
        "Local loopback study loop",
        'href="/docs">API docs</a>',
        'id="deck-select"',
        'id="deck-id"',
        'id="load-next-btn"',
        'id="refresh-decks-btn"',
        'id="study-card"',
        'id="reveal-btn"',
        'id="templates-section"',
        'id="errors-section"',
        'src="/static/study.js"',
        "color-scheme: light;",
        "#ffffff",
        "#000000",
        "#c62828",
        "#2e7d32",
        "#0000ee",
        "#f2f2f2",
        "#f7f7f7",
        "#dfdfdf",
        "#cfcfcf",
    ):
        assert expected in html
    for quality in range(6):
        assert f'data-quality="{quality}"' in html

    script = client.get("/static/study.js")
    assert script.status_code == 200
    js = script.text
    assert "/study/next?deck_id=" in js
    assert "/reveal" in js
    assert "/grade" in js
    assert "/templates" in js
    assert "/errors" in js
    assert "/due" not in js


def test_ui_does_not_embed_due_card_answers_in_initial_html(client):
    deck_id = client.post("/decks", json={"name": "Recall Check"}).json()["id"]
    card = client.post(
        "/cards",
        json={
            "deck_id": deck_id,
            "front": "SECRET_FRONT_PROMPT_901",
            "back": "SECRET_BACK_ANSWER_902",
            "accepted_answers": ["SECRET_ACCEPTED_903"],
            "explanation": "SECRET_EXPLANATION_904",
        },
    )
    assert card.status_code == 201

    html = client.get("/ui").text
    for secret in (
        "SECRET_FRONT_PROMPT_901",
        "SECRET_BACK_ANSWER_902",
        "SECRET_ACCEPTED_903",
        "SECRET_EXPLANATION_904",
    ):
        assert secret not in html


def test_ui_routes_do_not_collide_with_existing_api_routes(client):
    assert client.get("/health").status_code == 200
    assert client.get("/decks").status_code == 200
    assert client.get("/templates").status_code == 200
    assert client.get("/errors").status_code == 200
    assert client.get("/docs").status_code == 200
