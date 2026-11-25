"""Browser regressions. Run with uv run --with playwright python -m pytest ui_tests."""

import json
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
ORIGIN = "http://127.0.0.1:8001"
BIG = 9007199254740993


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    page = browser.new_page(viewport={"width": 320, "height": 700})
    page.route("**/*", lambda route: route.abort())
    page.route("**/ui", lambda r: r.fulfill(path=STATIC / "study.html"))
    page.route("**/static/study.js", lambda r: r.fulfill(path=STATIC / "study.js"))
    yield page
    page.close()


@pytest.mark.parametrize("typed", [True, False], ids=["manual", "api"])
def test_large_deck_id_reaches_both_writes_exactly(page, typed):
    template = {"id": "tpl", "category": "grammar", "title": "Example"}
    error = {"id": BIG + 2, "status": "draft", "attempted": "a", "corrected": "b", "rationale": "c"}
    decks = [] if typed else [{"id": BIG, "name": "Large"}]
    page.route("**/decks", lambda r: r.fulfill(json=decks))
    page.route("**/study/next?*", lambda r: r.fulfill(status=204))
    page.route("**/templates", lambda r: r.fulfill(json=[template]))
    page.route("**/templates/tpl", lambda r: r.fulfill(json=template))
    page.route("**/templates/tpl/cards", lambda r: r.fulfill(json={"id": BIG}))
    page.route("**/errors?*", lambda r: r.fulfill(json=[error]))
    page.route("**/approve", lambda r: r.fulfill(json={"card": {"id": BIG}}))
    page.goto(f"{ORIGIN}/ui")
    deck = page.locator("#deck-id")
    if typed:
        deck.fill(str(BIG))
    expect(deck).to_have_value(str(BIG))
    page.locator("#templates-section summary").click()
    page.locator("#template-select").select_option("tpl")
    with page.expect_request("**/templates/tpl/cards") as create:
        page.locator("#create-from-template-btn").click()
    assert str(json.loads(create.value.post_data)["deck_id"]) == str(BIG)
    expect(page.locator("#templates-status")).to_contain_text(str(BIG))
    page.locator("#errors-section summary").click()
    with page.expect_request("**/approve") as approve:
        page.locator("#errors-list button").first.click()
    assert approve.value.url.endswith(f"/errors/{BIG + 2}/approve")
    assert str(json.loads(approve.value.post_data)["deck_id"]) == str(BIG)


def prompt(card_id=BIG, deck_id=BIG):
    return {
        "card_id": card_id,
        "deck_id": deck_id,
        "kind": "basic",
        "front": "What does DNS do?",
        "due_date": "2026-11-25",
        "repetitions": 0,
        "interval_days": 1,
        "ease_factor": 2.5,
    }


def test_keyboard_loop_and_mobile_layout(page):
    grades = []
    page.route("**/decks", lambda r: r.fulfill(json=[{"id": BIG, "name": "Networks"}]))
    page.route("**/study/next?*", lambda r: r.fulfill(json=prompt()))
    page.route(f"**/study/{BIG}/reveal", lambda r: r.fulfill(json={"back": "Resolve names"}))

    def grade(route):
        grades.append(route.request.post_data_json)
        route.fulfill(json={"due_date": "2026-11-26", "interval_days": 1})

    page.route(f"**/study/{BIG}/grade", grade)
    page.goto(f"{ORIGIN}/ui")
    expect(page.locator("html")).to_have_attribute("lang", "es")
    deck = page.locator("#deck-id")
    deck.focus()
    deck.press("End")
    deck.press("4")
    expect(deck).to_have_value(f"{BIG}4")
    deck.fill(str(BIG))
    deck.press("Enter")
    reveal = page.get_by_role("button", name="Mostrar respuesta")
    expect(reveal).to_be_focused()
    reveal.press("4")
    expect(page.locator("#answer-panel")).to_be_hidden()
    reveal.press("r")
    answer = page.locator("#card-back")
    expect(answer).to_have_text("Resolve names")
    expect(answer).to_be_focused()
    answer.press("4")
    expect(page.locator("#study-status")).to_contain_text("Calificación: 4")
    expect(reveal).to_be_focused()
    assert grades == [{"quality": 4}]
    assert page.evaluate("document.documentElement.scrollWidth === innerWidth")


def test_clear_selection_while_refreshing(page):
    refresh = []
    page.route("**/decks", lambda r: r.fulfill(json=[{"id": 1, "name": "First"}]))
    page.route("**/study/next?*", lambda r: r.fulfill(json=prompt(1, 1)))
    page.goto(f"{ORIGIN}/ui")
    expect(page.locator("#study-card")).to_be_visible()
    page.route("**/decks", lambda r: refresh.append(r))
    with page.expect_request("**/decks"):
        page.locator("#refresh-decks-btn").click()
    page.locator("#deck-select").select_option("")
    with page.expect_event("requestfinished", predicate=lambda req: req.url.endswith("/decks")):
        refresh[0].fulfill(json=[{"id": 1, "name": "First"}])
    expect(page.locator("#deck-id")).to_have_value("")
    expect(page.locator("#study-card")).to_be_hidden()


def test_edit_deck_during_reveal(page):
    inflight = []
    page.route("**/decks", lambda r: r.fulfill(json=[{"id": BIG, "name": "First"}]))
    page.route("**/study/next?*", lambda r: r.fulfill(json=prompt()))
    page.route("**/reveal", lambda r: inflight.append(r))
    page.goto(f"{ORIGIN}/ui")
    with page.expect_request("**/reveal"):
        page.locator("#reveal-btn").click()
    page.locator("#deck-id").fill("2")
    with page.expect_event("requestfinished", predicate=lambda req: req.url.endswith("/reveal")):
        inflight[0].fulfill(json={"back": "Old answer"})
    expect(page.locator("#card-back")).to_be_empty()
    expect(page.locator("#study-card")).to_be_hidden()
