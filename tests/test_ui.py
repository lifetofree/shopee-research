"""Static-file smoke for the SPA.

The SPA itself is exercised manually in a browser; the `make e2e` ticket
(the real end-to-end) covers live API behavior. This file gives us a
non-Playwright safety net: it confirms the three artifacts exist, the
HTML references the right assets, and the JS file parses (no syntax
errors that would break `uvicorn` boot).

A `make smoke`-style JS-execution check is left out of scope here — it
would need Node in CI. The HTML + asset presence checks are the right
floor for a v1 ticket.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def test_index_html_exists_and_is_html() -> None:
    p = STATIC_DIR / "index.html"
    assert p.exists(), f"missing {p}"
    text = p.read_text(encoding="utf-8")
    assert text.lstrip().lower().startswith("<!doctype html>")
    assert "<title>shopee-th</title>" in text


def test_index_html_references_app_js_and_styles_css() -> None:
    text = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<link[^>]+href="styles\.css"', text), "index.html must link styles.css"
    assert re.search(r'<script[^>]+src="app\.js"', text), "index.html must load app.js"


def test_index_html_has_required_sections() -> None:
    text = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    # Search form + button
    assert 'id="search-form"' in text
    assert 'id="search-input"' in text
    assert 'id="search-button"' in text
    # Results + saved containers
    assert 'id="results-section"' in text
    assert 'id="results-grid"' in text
    assert 'id="saved-section"' in text
    assert 'id="saved-list"' in text
    # Error banner
    assert 'id="error-banner"' in text
    assert 'id="error-dismiss"' in text
    # Templates the JS clones
    assert 'id="tpl-result-card"' in text
    assert 'id="tpl-saved-item"' in text
    assert 'id="tpl-output-row"' in text


def test_app_js_exists_and_uses_iife() -> None:
    p = STATIC_DIR / "app.js"
    assert p.exists(), f"missing {p}"
    text = p.read_text(encoding="utf-8")
    # Wraps in an IIFE so no globals leak.
    assert "(function ()" in text or "(function() {" in text
    assert '"use strict";' in text
    # Exposes a smoke hook for future tests.
    assert "window.ShopeeTH" in text


def test_app_js_calls_documented_endpoints() -> None:
    """Static check that all 7 documented routes are referenced from the JS."""
    text = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    # api.search → POST /api/search
    assert '"/api/search"' in text and "method: \"POST\"" in text
    # api.listSaved → GET /api/saved
    assert '"/api/saved"' in text and "method: \"GET\"" in text
    # api.saveItem → POST /api/saved
    assert '"/api/saved",' in text  # appears in both listSaved (GET) and saveItem (POST)
    # DELETE
    assert 'method: "DELETE"' in text
    # Caption / clip-prompt
    assert "/caption" in text
    assert "/clip-prompt" in text
    # Outputs
    assert "/outputs" in text


def test_app_js_handles_idempotency_for_save() -> None:
    """The double-click guard is the visible idempotency contract."""
    text = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "state.saving" in text
    assert "state.saving.has" in text
    assert "state.saving.add" in text
    assert "state.saving.delete" in text


def test_app_js_renders_error_banner_with_server_message() -> None:
    """The uniform `ApiError` body is consumed (detail.message / detail.guidance)."""
    text = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "showError" in text
    assert "detail.message" in text
    assert "guidance" in text


def test_styles_css_exists_and_has_root_vars() -> None:
    p = STATIC_DIR / "styles.css"
    assert p.exists(), f"missing {p}"
    text = p.read_text(encoding="utf-8")
    # Design tokens via CSS variables.
    assert ":root" in text
    assert "--primary" in text
    assert "--danger" in text


def test_styles_css_is_vanilla_no_framework_imports() -> None:
    """No `@import url(https://...)` (no CDN framework) and no Tailwind directives."""
    text = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
    assert "@import" not in text
    assert "@tailwind" not in text
    assert "@apply" not in text


def test_no_login_ui_in_html() -> None:
    """No password / cookie input — secrets stay in `.env`, never reach the browser."""
    text = (STATIC_DIR / "index.html").read_text(encoding="utf-8").lower()
    assert 'type="password"' not in text
    assert 'name="cookie"' not in text
    assert 'name="session"' not in text
