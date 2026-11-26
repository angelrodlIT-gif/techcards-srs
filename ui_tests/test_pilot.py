"""Browser regressions. Run with uv run --with playwright python -m pytest ui_tests."""

import json
from pathlib import Path
from urllib.parse import urlsplit

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
    page.route("**/decks?*", lambda r: r.fulfill(json=decks))
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
    page.route("**/decks?*", lambda r: r.fulfill(json=[{"id": BIG, "name": "Networks"}]))
    page.route("**/study/next?*", lambda r: r.fulfill(json=prompt(BIG + 2 if grades else BIG)))
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
    page.route("**/decks?*", lambda r: r.fulfill(json=[{"id": 1, "name": "First"}]))
    page.route("**/study/next?*", lambda r: r.fulfill(json=prompt(1, 1)))
    page.goto(f"{ORIGIN}/ui")
    expect(page.locator("#study-card")).to_be_visible()
    page.route("**/decks?*", lambda r: refresh.append(r))
    with page.expect_request("**/decks?*"):
        page.locator("#refresh-decks-btn").click()
    page.locator("#deck-select").select_option("")
    with page.expect_event(
        "requestfinished", predicate=lambda req: urlsplit(req.url).path == "/decks"
    ):
        refresh[0].fulfill(json=[{"id": 1, "name": "First"}])
    expect(page.locator("#deck-id")).to_have_value("")
    expect(page.locator("#study-card")).to_be_hidden()


def test_edit_deck_during_reveal(page):
    inflight = []
    page.route("**/decks?*", lambda r: r.fulfill(json=[{"id": BIG, "name": "First"}]))
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


def test_large_successful_write_in_legacy_browser_cannot_be_repeated(page):
    # Older engines call revivers with only the key and already-rounded value.
    page.add_init_script("""{
      const parse = JSON.parse;
      JSON.parse = (raw, reviver) => parse(raw, reviver && function(key, value) {
        return reviver.call(this, key, value);
      });
    }""")
    requests = []
    title = 'Practice "id": 9007199254740993, including a literal backslash: \\'
    template = {"id": "tpl", "category": "grammar", "title": title}

    def created(route):
        requests.append(route.request.post_data_json)
        route.fulfill(status=201, json={"id": BIG, "front": title})

    page.route("**/decks?*", lambda r: r.fulfill(json=[{"id": 1, "name": "First"}]))
    page.route("**/study/next?*", lambda r: r.fulfill(status=204))
    page.route("**/templates", lambda r: r.fulfill(json=[template]))
    page.route("**/templates/tpl", lambda r: r.fulfill(json=template))
    page.route("**/templates/tpl/cards", created)
    page.goto(f"{ORIGIN}/ui")
    page.locator("#templates-section summary").click()
    page.locator("#template-select").select_option("tpl")
    expect(page.locator("#tpl-title")).to_have_text(title)
    create = page.locator("#create-from-template-btn")
    create.click()
    expect(page.locator("#templates-status")).to_contain_text(f"Tarjeta #{BIG} creada")
    expect(create).to_be_disabled()
    page.locator("#template-select").select_option("")
    page.locator("#template-select").select_option("tpl")
    expect(create).to_be_disabled()
    assert requests == [{"deck_id": "1"}]


def test_destinations_follow_picker_manual_id_and_invalid_input(page):
    template = {"id": "tpl", "category": "grammar", "title": "Example"}
    error = {"id": 8, "status": "draft", "attempted": "a", "corrected": "b", "rationale": "c"}
    page.route("**/decks?*", lambda r: r.fulfill(json=[{"id": BIG, "name": "Redes"}]))
    page.route("**/study/next?*", lambda r: r.fulfill(status=204))
    page.route("**/templates", lambda r: r.fulfill(json=[template]))
    page.route("**/templates/tpl", lambda r: r.fulfill(json=template))
    page.route("**/errors?*", lambda r: r.fulfill(json=[error]))
    page.goto(f"{ORIGIN}/ui")
    page.locator("#templates-section summary").click()
    page.locator("#template-select").select_option("tpl")
    page.locator("#errors-section summary").click()
    create = page.locator("#create-from-template-btn")
    approve = page.get_by_role("button", name="Aprobar y crear tarjeta")
    for button in (create, approve):
        expect(button).to_have_accessible_description(f"Destino: Redes (#{BIG})")
    page.locator("#deck-id").fill(str(BIG + 2))
    for button in (create, approve):
        expect(button).to_have_accessible_description(f"Destino: mazo #{BIG + 2}")
    page.locator("#deck-id").fill("-")
    for button in (create, approve):
        expect(button).to_be_disabled()
    page.locator("#deck-select").select_option(str(BIG))
    for button in (create, approve):
        expect(button).to_be_enabled()
        expect(button).to_have_accessible_description(f"Destino: Redes (#{BIG})")


def test_search_reaches_later_pages_without_switching_decks(page):
    decks = [{"id": i, "name": f"Deck {i}"} for i in range(1, 101)]
    page.route("**/decks?offset=0&limit=100", lambda r: r.fulfill(json=decks))
    page.route(
        "**/decks?offset=100&limit=100", lambda r: r.fulfill(json=[{"id": BIG, "name": "DNS"}])
    )
    page.route("**/study/next?*", lambda r: r.fulfill(status=204))
    page.goto(f"{ORIGIN}/ui")
    select = page.locator("#deck-select")
    expect(select.locator("option")).to_have_count(102)
    page.get_by_label("Buscar mazo").fill("dns")
    expect(page.locator("#deck-list-status")).to_have_text("Coincidencias: 1.")
    expect(select).to_have_value("1")
    select.select_option(str(BIG))
    expect(page.locator("#deck-id")).to_have_value(str(BIG))
    page.get_by_label("Buscar mazo").fill("not found")
    expect(page.locator("#deck-list-status")).to_have_text("Coincidencias: 0.")
    expect(select).to_have_value(str(BIG))
    page.get_by_label("Buscar mazo").fill("4740993")
    expect(page.locator("#deck-list-status")).to_have_text("Coincidencias: 1.")


@pytest.mark.parametrize("switch", [False, True], ids=["select-new", "preserve-user-choice"])
def test_create_first_deck_inline(page, switch):
    catalog = []
    writes = []
    page.route("**/decks?*", lambda r: r.fulfill(json=catalog))
    page.route("**/decks", lambda r: writes.append(r))
    page.route("**/study/next?*", lambda r: r.fulfill(status=204))
    page.goto(f"{ORIGIN}/ui")
    expect(page.locator("#deck-list-status")).to_contain_text("Aún no hay mazos")
    page.get_by_text("Crear un mazo", exact=True).click()
    name = page.get_by_label("Nombre del mazo")
    name.fill("  Redes  ")
    create = page.get_by_role("button", name="Crear mazo")
    with page.expect_request("**/decks"):
        create.click()
    expect(create).to_be_disabled()
    assert writes[0].request.post_data_json == {"name": "Redes"}
    if switch:
        page.locator("#deck-id").fill("14")
    catalog.append({"id": BIG, "name": "Redes"})
    writes[0].fulfill(status=201, json=catalog[0])
    expect(page.locator("#deck-create-status")).to_contain_text(f"Mazo «Redes» creado (#{BIG})")
    expect(page.locator("#deck-id")).to_have_value("14" if switch else str(BIG))
    expect(page.locator("#deck-select option")).to_have_count(2)
    expect(create).to_be_enabled()
    expect(name).to_be_empty()
    assert len(writes) == 1


def test_uncertain_deck_creation_blocks_repeated_submit(page):
    posts = []

    def interrupted(route):
        posts.append(route.request.post_data_json)
        route.abort()

    page.route("**/decks?*", lambda r: r.fulfill(json=[]))
    page.route("**/decks", interrupted)
    page.goto(f"{ORIGIN}/ui")
    page.get_by_text("Crear un mazo", exact=True).click()
    page.get_by_label("Nombre del mazo").fill("Redes")
    submit = page.get_by_role("button", name="Crear mazo")
    submit.click()
    expect(page.locator("#deck-create-status")).to_contain_text("No se pudo confirmar")
    submit.click()
    assert posts == [{"name": "Redes"}]


def test_uncertain_template_write_stays_locked_for_its_destination(page):
    template = {"id": "tpl", "category": "grammar", "title": "Example"}
    page.route("**/decks?*", lambda r: r.fulfill(json=[{"id": 1, "name": "First"}]))
    page.route("**/study/next?*", lambda r: r.fulfill(status=204))
    page.route("**/templates", lambda r: r.fulfill(json=[template]))
    page.route("**/templates/tpl", lambda r: r.fulfill(json=template))
    page.route("**/templates/tpl/cards", lambda r: r.fulfill(status=201, body="{"))
    page.goto(f"{ORIGIN}/ui")
    page.locator("#templates-section summary").click()
    page.locator("#template-select").select_option("tpl")
    create = page.locator("#create-from-template-btn")
    create.click()
    expect(page.locator("#templates-status")).to_contain_text("No se pudo confirmar")
    expect(create).to_be_disabled()
    page.locator("#deck-id").fill("2")
    expect(create).to_be_enabled()
    page.locator("#deck-id").fill("1")
    expect(create).to_be_disabled()


@pytest.mark.parametrize("outcome", ["lost", "unreadable", "confirmed"])
def test_grade_refreshes_without_repeating_the_same_due_review(page, outcome):
    posts = []
    card = prompt()

    def grade(route):
        posts.append(route.request.post_data_json)
        if outcome == "lost":
            route.abort()
        elif outcome == "unreadable":
            route.fulfill(status=201, body="{")
        else:
            route.fulfill(status=201, json={"due_date": "2026-11-26", "interval_days": 1})

    page.route("**/decks?*", lambda r: r.fulfill(json=[{"id": BIG, "name": "First"}]))
    page.route("**/study/next?*", lambda r: r.fulfill(json=card))
    page.route("**/reveal", lambda r: r.fulfill(json={"back": "Answer"}))
    page.route("**/grade", grade)
    page.goto(f"{ORIGIN}/ui")
    page.locator("#reveal-btn").click()
    with page.expect_request("**/study/next?*", timeout=3000):
        page.locator('[data-quality="4"]').click()
    expect(page.locator("#study-status")).to_contain_text("Este repaso está bloqueado")
    expect(page.locator("#study-card")).to_be_hidden()
    if outcome != "confirmed":
        expect(page.locator("#study-status")).to_contain_text("No se pudo confirmar")
    page.locator("#load-next-btn").click()
    expect(page.locator("#study-card")).to_be_hidden()
    # The same card is eligible again for its next scheduled occurrence.
    card["due_date"] = "2026-11-26"
    page.locator("#load-next-btn").click()
    page.locator("#reveal-btn").click()
    expect(page.locator('[data-quality="4"]')).to_be_enabled()
    assert posts == [{"quality": 4}]


@pytest.mark.parametrize("outcome", ["lost", "unreadable", "confirmed"])
def test_draft_refreshes_and_locks_only_the_same_contents(page, outcome):
    posts = []
    draft = {"attempted": "a", "corrected": "b", "rationale": "c"}

    def create(route):
        posts.append(route.request.post_data_json)
        if outcome == "lost":
            route.abort()
        elif outcome == "unreadable":
            route.fulfill(status=201, body="{")
        else:
            route.fulfill(status=201, json={"id": BIG})

    page.route("**/decks?*", lambda r: r.fulfill(json=[]))
    page.route("**/errors?*", lambda r: r.fulfill(json=[]))
    page.route("**/errors", create)
    page.goto(f"{ORIGIN}/ui")
    page.locator("#errors-section summary").click()
    expect(page.locator("#errors-status")).to_contain_text("Errores encontrados")
    for field, value in draft.items():
        page.locator(f"#err-{field}").fill(value)
    submit = page.get_by_role("button", name="Guardar borrador")
    with page.expect_request("**/errors?*", timeout=3000):
        submit.click()
    if outcome != "confirmed":
        expect(page.locator("#draft-status")).to_contain_text("No se pudo confirmar")
        expect(page.locator("#err-attempted")).to_have_value("a")
    for field, value in draft.items():
        page.locator(f"#err-{field}").fill(value + " ")
    expect(submit).to_be_disabled()
    page.locator("#error-form").evaluate("(form) => form.requestSubmit()")
    page.locator("#err-rationale").fill("Different reason")
    expect(submit).to_be_enabled()
    assert posts == [draft]


def test_validation_rejections_leave_grade_and_draft_correctable(page):
    def reject(route):
        route.fulfill(status=422, json={"detail": "Entrada no válida"})

    page.route("**/decks?*", lambda r: r.fulfill(json=[{"id": BIG, "name": "First"}]))
    page.route("**/study/next?*", lambda r: r.fulfill(json=prompt()))
    page.route("**/reveal", lambda r: r.fulfill(json={"back": "Answer"}))
    page.route("**/grade", reject)
    page.route("**/errors?*", lambda r: r.fulfill(json=[]))
    page.route("**/errors", reject)
    page.goto(f"{ORIGIN}/ui")
    page.locator("#reveal-btn").click()
    page.locator('[data-quality="4"]').click()
    expect(page.locator("#study-status")).to_have_text("Entrada no válida")
    expect(page.locator('[data-quality="3"]')).to_be_enabled()
    page.locator("#errors-section summary").click()
    for field in ("attempted", "corrected", "rationale"):
        page.locator(f"#err-{field}").fill(field)
    submit = page.get_by_role("button", name="Guardar borrador")
    submit.click()
    expect(page.locator("#draft-status")).to_have_text("Entrada no válida")
    expect(submit).to_be_enabled()
    expect(page.locator("#err-attempted")).to_have_value("attempted")


@pytest.mark.parametrize(("width", "font_scale"), [(320, 1), (1024, 1), (320, 2)])
def test_long_study_content_fits(page, width, font_scale):
    page.set_viewport_size({"width": width, "height": 700})
    name = "👩🏽‍💻 " + "DistributedSystemsCertification" * 3
    token = "bartholomew.fitzgerald@northwind-industries-holdings.example.com"
    # Test-only switch, also usable with Playwright's interactive inspector.
    page.add_init_script("""document.addEventListener('DOMContentLoaded', () => {
        const picker = document.createElement('select');
        picker.setAttribute('aria-label', 'Test data');
        for (const label of ['Demo data', 'Worst case', 'Empty']) picker.add(new Option(label));
        picker.value = new URLSearchParams(location.search).get('data') || 'Demo data';
        picker.onchange = () => { location.search = new URLSearchParams({data: picker.value}); };
        Object.assign(picker.style, {position: 'fixed', bottom: '0', left: '50%',
                                     transform: 'translateX(-50%)', zIndex: '1'});
        document.body.append(picker);
    });""")
    page.route("**/ui?*", lambda r: r.fulfill(path=STATIC / "study.html"))

    def decks(route):
        rows = [{"id": BIG, "name": name if "Worst" in page.url else "Redes"}]
        route.fulfill(json=[] if "Empty" in page.url else rows)

    page.route("**/decks?*", decks)
    page.route(
        "**/study/next?*",
        lambda r: r.fulfill(
            json=dict(prompt(), repetitions=2147483647, source_label=token)
            if "Worst" in page.url
            else prompt()
        ),
    )
    page.route(
        "**/reveal",
        lambda r: r.fulfill(
            json={"back": name, "accepted_answers": [token]}
            if "Worst" in page.url
            else {"back": "Redes"}
        ),
    )
    page.goto(f"{ORIGIN}/ui")
    expect(page.locator("#card-meta")).to_contain_text("repasos: 0")
    picker = page.get_by_label("Test data")
    picker.select_option(label="Empty")
    expect(page.locator("#deck-list-status")).to_contain_text("Aún no hay mazos")
    picker.select_option(label="Worst case")
    page.locator("#reveal-btn").click()
    page.locator("html").evaluate(
        "(el, scale) => el.style.fontSize = 16 * scale + 'px'", font_scale
    )
    expect(page.locator("#card-back")).to_have_text(name)
    expect(page.locator("#card-meta")).to_contain_text(f"Tarjeta #{BIG}")
    expect(page.locator("#card-meta")).to_contain_text("2147483647")
    for selector in ("#card-meta", "#card-accepted", "html"):
        assert page.locator(selector).evaluate("el => el.scrollWidth <= el.clientWidth"), selector


@pytest.mark.parametrize("reduced", [False, True], ids=["standard", "reduced"])
def test_form_press_feedback(page, reduced):
    page.emulate_media(reduced_motion="reduce" if reduced else "no-preference")
    page.route("**/decks?*", lambda r: r.fulfill(json=[]))
    page.goto(f"{ORIGIN}/ui")
    page.locator("#new-deck summary").click()
    button = page.get_by_role("button", name="Crear mazo")
    button.hover()
    page.mouse.down()
    if reduced:
        expect(button).to_have_css("transform", "none")
    else:
        expect(button).to_have_css("transform", "matrix(0.97, 0, 0, 0.97, 0, 0)")
        expect(button).to_have_css("transition-duration", "0.16s")
    page.mouse.up()
    if not reduced:
        expect(button).to_have_css("transition-duration", "0.1s")
    page.get_by_label("Nombre del mazo").focus()
    page.keyboard.press("Tab")
    expect(button).to_be_focused()
    page.keyboard.down("Space")
    expect(button).to_have_css("transition-duration", "0s")
    expect(button).to_have_css("transform", "none")
    page.keyboard.up("Space")
