"""Optional Playwright smoke test for the Cabina UI (/ui/).

Run without adding Playwright to project dependencies:
    uv run --no-project --with playwright python scripts/ui_smoke.py --base http://127.0.0.1:8004

By default, interactive grading runs in Demo mode (`?data=demo`) so running this
smoke test never mutates real SM-2 study schedules.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.request import urlopen

from playwright.sync_api import (
    Browser,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    Error as PlaywrightError,
)

VIEWPORTS = (
    ("desktop", 1280, 800),
    ("mobile", 390, 844),
)


def fetch_review_count(base: str) -> int:
    with urlopen(f"{base}/analytics/learning", timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return int(data["reviews"]["recall"]["denominator"])


def assert_no_horizontal_overflow(page: Page, context: str) -> None:
    metrics = page.evaluate(
        "() => ({"
        " scrollWidth: document.documentElement.scrollWidth,"
        " innerWidth: window.innerWidth"
        " })"
    )
    if metrics["scrollWidth"] > metrics["innerWidth"]:
        raise AssertionError(
            f"Horizontal overflow on {context}: "
            f"scrollWidth={metrics['scrollWidth']} > innerWidth={metrics['innerWidth']}"
        )


def click_nav(page: Page, view: str, is_mobile: bool) -> None:
    selector = (
        f".mobile-tabbar [data-view='{view}']" if is_mobile else f".sidebar [data-view='{view}']"
    )
    page.locator(selector).click()


def run_viewport_smoke(
    page: Page, base: str, name: str, width: int, height: int, *, live_grade: bool = False
) -> None:
    is_mobile = width < 960
    page.set_viewport_size({"width": width, "height": height})

    # 1. Start at /ui (redirect -> /ui/) and verify home view (read-only on real API)
    page.goto(f"{base}/ui", wait_until="networkidle")
    if not page.url.rstrip("/").endswith("/ui"):
        raise AssertionError(f"Expected redirect to /ui/, got {page.url}")
    page.locator(".cockpit-hero").wait_for(state="visible", timeout=10000)
    assert_no_horizontal_overflow(page, f"{name}:dashboard")

    # Open first deck inspector & verify Edit Card modal opens cleanly (without submitting)
    inspect_btn = page.locator(".deck-tile button", has_text="Tarjetas").first
    if inspect_btn.count() > 0:
        inspect_btn.click()
        modal = page.locator("#modal-backdrop")
        modal.wait_for(state="visible", timeout=5000)
        assert_no_horizontal_overflow(page, f"{name}:deck-inspector")
        edit_card_btn = modal.locator("button", has_text="Editar").nth(1)
        if edit_card_btn.count() > 0:
            edit_card_btn.click()
            page.locator("#modal-title").wait_for(state="visible", timeout=5000)
            assert_no_horizontal_overflow(page, f"{name}:edit-card-modal")
        page.locator("#modal-close-btn").click()
        modal.wait_for(state="hidden", timeout=5000)

    # 2. Command Palette (Ctrl+K) -> jump to Templates gallery
    page.keyboard.press("Control+k")
    palette = page.locator("#command-palette-backdrop")
    palette.wait_for(state="visible", timeout=5000)
    cmd_input = page.locator("#cmd-input")
    cmd_input.fill("Plantillas")
    cmd_input.press("Enter")
    palette.wait_for(state="hidden", timeout=5000)
    page.get_by_role("tab", name="Plantillas").wait_for(state="visible", timeout=5000)
    assert_no_horizontal_overflow(page, f"{name}:templates")

    # Verify Sources tab renders cleanly
    page.get_by_role("tab", name="Fuentes").click()
    assert_no_horizontal_overflow(page, f"{name}:sources")

    # Verify Esc closes Command Palette cleanly
    page.keyboard.press("Control+k")
    palette.wait_for(state="visible", timeout=5000)
    page.keyboard.press("Escape")
    palette.wait_for(state="hidden", timeout=5000)

    # 3. Errors board (verify draft edit modal opens cleanly without submitting)
    click_nav(page, "errors", is_mobile)
    page.get_by_role("heading", name="Tablero de errores").wait_for(state="visible", timeout=5000)
    assert_no_horizontal_overflow(page, f"{name}:errors")

    edit_err_btn = page.locator(".error-card-actions button", has_text="Editar").first
    if edit_err_btn.count() > 0:
        edit_err_btn.click()
        modal = page.locator("#modal-backdrop")
        modal.wait_for(state="visible", timeout=5000)
        assert_no_horizontal_overflow(page, f"{name}:edit-error-modal")
        page.locator("#modal-close-btn").click()
        modal.wait_for(state="hidden", timeout=5000)

    # 4. Analytics view
    click_nav(page, "analytics", is_mobile)
    page.get_by_role("heading", name="Analítica de aprendizaje").wait_for(
        state="visible", timeout=5000
    )
    assert_no_horizontal_overflow(page, f"{name}:analytics")

    # 5. Focus mode initial render on live view (read-only), then grade in Demo by default
    click_nav(page, "study", is_mobile)
    page.locator(".focus-shell").wait_for(state="visible", timeout=5000)
    page.locator("#reveal-btn, .focus-shell .empty-state").first.wait_for(
        state="visible", timeout=5000
    )
    assert_no_horizontal_overflow(page, f"{name}:study-live-initial")

    reveal_btn = page.locator("#reveal-btn")
    if not live_grade or reveal_btn.count() == 0:
        page.goto(f"{base}/ui/?data=demo", wait_until="networkidle")
        # Verify switching out of Demo invalidates open Demo dialogs immediately
        if not is_mobile:
            page.locator(".deck-tile button", has_text="Tarjetas").first.click()
            modal = page.locator("#modal-backdrop")
            modal.wait_for(state="visible", timeout=5000)
            modal.locator("button", has_text="Eliminar mazo").click()
            page.keyboard.press("Control+k")
            palette.wait_for(state="visible", timeout=5000)
            cmd_input.fill("Volver a API real")
            cmd_input.press("Enter")
            modal.wait_for(state="hidden", timeout=5000)
            page.goto(f"{base}/ui/?data=demo", wait_until="networkidle")

        click_nav(page, "study", is_mobile)
        page.locator(".focus-shell").wait_for(state="visible", timeout=5000)
        reveal_btn.wait_for(state="visible", timeout=5000)
        assert_no_horizontal_overflow(page, f"{name}:study-demo-initial")

    # Blur any focused button so Space triggers the keyboard shortcut handler cleanly
    prompt_before = page.locator(".study-prompt").text_content() or ""
    page.evaluate("() => document.activeElement?.blur()")
    page.keyboard.press("Space")
    page.locator(".study-answer-panel").wait_for(state="visible", timeout=5000)
    page.locator(".grade-dock").wait_for(state="visible", timeout=5000)
    assert_no_horizontal_overflow(page, f"{name}:study-revealed")

    page.keyboard.press("4")
    page.locator(".study-answer-panel").wait_for(state="hidden", timeout=5000)
    assert_no_horizontal_overflow(page, f"{name}:study-after-grade")

    if page.locator(".study-prompt").count() > 0:
        prompt_after = page.locator(".study-prompt").text_content() or ""
        if prompt_after == prompt_before:
            raise AssertionError("Expected grade shortcut '4' to advance to the next card")

    # Verify exiting Demo during revealed Focus Mode clears the Demo card cleanly
    if not live_grade and not is_mobile and page.locator("#reveal-btn").count() > 0:
        page.evaluate("() => document.activeElement?.blur()")
        page.keyboard.press("Space")
        page.locator(".study-answer-panel").wait_for(state="visible", timeout=5000)
        page.keyboard.press("Control+k")
        palette.wait_for(state="visible", timeout=5000)
        cmd_input.fill("Volver a API real")
        cmd_input.press("Enter")
        page.locator(".study-answer-panel").wait_for(state="hidden", timeout=5000)

    page.keyboard.press("Escape")
    page.locator(".focus-shell").wait_for(state="hidden", timeout=5000)
    assert_no_horizontal_overflow(page, f"{name}:after-esc-dashboard")


def launch_browser(playwright: Playwright) -> Browser:
    try:
        return playwright.chromium.launch()
    except PlaywrightError:
        return playwright.chromium.launch(channel="chrome")


def main() -> int:
    # Chrome Unix domain sockets fail when TMPDIR is too long (> ~50 chars).
    if len(os.environ.get("TMPDIR", "")) > 40 and os.path.isdir("/tmp"):
        os.environ["TMPDIR"] = "/tmp"

    parser = argparse.ArgumentParser(description="Playwright smoke test for TechCards Cabina UI")
    parser.add_argument(
        "--base", default="http://127.0.0.1:8004", help="Base URL of the API server"
    )
    parser.add_argument(
        "--live-grade",
        action="store_true",
        help="Grade real cards instead of switching to Demo mode for the Focus Mode grading step",
    )
    args = parser.parse_args()
    base = args.base.rstrip("/")

    reviews_before = fetch_review_count(base)
    page_errors: list[str] = []
    console_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        context = browser.new_context()
        page = context.new_page()
        page.on("pageerror", lambda err: page_errors.append(str(err)))
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )

        # Verify legacy /propuesta3 alias redirect
        page.goto(f"{base}/propuesta3", wait_until="networkidle")
        if not page.url.rstrip("/").endswith("/ui"):
            raise AssertionError(f"Expected /propuesta3 redirect to /ui/, got {page.url}")

        for name, width, height in VIEWPORTS:
            run_viewport_smoke(page, base, name, width, height, live_grade=args.live_grade)
            print(f"[ok] {name} ({width}x{height}): home, Ctrl+K, templates, errors, focus mode")

        browser.close()

    if not args.live_grade:
        reviews_after = fetch_review_count(base)
        if reviews_after != reviews_before:
            raise AssertionError(
                f"Smoke test mutated real reviews without --live-grade: "
                f"{reviews_before} -> {reviews_after}"
            )

    if page_errors or console_errors:
        print(f"Page errors: {page_errors}", file=sys.stderr)
        print(f"Console errors: {console_errors}", file=sys.stderr)
        return 1

    print("[ok] UI smoke passed with 0 page/console errors and 0 horizontal overflow.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
