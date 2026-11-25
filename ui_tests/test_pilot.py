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
