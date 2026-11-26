"""Verification tests for Propuesta 1 static study UI (/propuesta1/)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROPUESTA1_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "propuesta1"

ASSETS = (
    "index.html",
    "styles.css",
    "app.js",
    "api.js",
    "demo-data.js",
    "ui.js",
    "views/dashboard.js",
    "views/study.js",
    "views/create.js",
    "views/errors.js",
    "views/analytics.js",
)


@pytest.mark.parametrize("asset", ASSETS)
def test_propuesta1_assets_served(client, asset):
    response = client.get(f"/propuesta1/{asset}")
    assert response.status_code == 200
    assert response.text.strip()


def test_propuesta1_design_doc_exists_and_is_not_served(client):
    design_doc = PROPUESTA1_DIR / "DESIGN.md"
    assert design_doc.is_file()
    assert "## 1. Exploración de conceptos" in design_doc.read_text(encoding="utf-8")
    assert client.get("/propuesta1/DESIGN.md").status_code == 404


def test_propuesta1_has_no_external_cdns_or_unsafe_innerhtml():
    html = (PROPUESTA1_DIR / "index.html").read_text(encoding="utf-8")
    css = (PROPUESTA1_DIR / "styles.css").read_text(encoding="utf-8")

    # No external stylesheet/script/font CDNs
    assert not re.search(r"https?://", html)
    assert not re.search(r"@import\s+url\(", css)

    # Relative asset links in index.html
    assert 'href="styles.css"' in html
    assert 'src="app.js"' in html

    # Mobile-native & accessibility guardrails
    assert "viewport-fit=cover" in html
    assert "user-scalable=no" not in html
    assert "maximum-scale=1" not in html
    assert 'name="theme-color"' in html

    assert "100dvh" in css
    assert "safe-area-inset-bottom" in css
    assert "font-size: 16px" in css
    assert "@media (hover: hover) and (pointer: fine)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "transition: all" not in css

    # Never assign user data via innerHTML in JS modules
    for rel in ASSETS:
        if rel.endswith(".js"):
            src = (PROPUESTA1_DIR / rel).read_text(encoding="utf-8")
            assert not re.search(r"\.innerHTML\s*=", src), f"Unexpected innerHTML write in {rel}"


def test_propuesta1_bigint_json_roundtrip():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available in environment")

    api_js_url = (PROPUESTA1_DIR / "api.js").resolve().as_uri()
    script = (
        f"import({api_js_url!r}).then((m) => {{"
        '  const raw = "{\\"id\\":9007199254740993123,\\"deck_id\\":9007199254740993124,'
        '\\"front\\":\\"text with \\\\\\"id\\\\\\":123 inside\\"}";'
        "  const parsed = m.parseApiJson(raw);"
        '  if (parsed.id !== "9007199254740993123") throw new Error("bad id");'
        '  if (parsed.deck_id !== "9007199254740993124") throw new Error("bad deck_id");'
        '  if (parsed.front !== \'text with "id":123 inside\') throw new Error("corrupted text");'
        '  const out = m.serializeApiJson({ deck_id: "9007199254740993124", max_cards: 6 });'
        '  if (out !== \'{"deck_id":9007199254740993124,"max_cards":6}\') {'
        '    throw new Error("bad serialized body: " + out);'
        "  }"
        "});"
    )
    proc = subprocess.run([node, "-e", script], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
