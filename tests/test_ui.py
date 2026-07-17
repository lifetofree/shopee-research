"""Static-file smoke for the SPA.

The SPA shows items captured by the browser extension (no more server-side
search box — capture happens in the extension). This file gives us a
non-Playwright safety net: confirms the three artifacts exist, the HTML
references the right assets, the JS parses, and the documented endpoints are
referenced.
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
    """The redesigned UI: saved-items grid is the focus. The dead search box
    is gone (capture happens in the browser extension now)."""
    text = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    # Saved-items containers (the core of the view)
    assert 'id="saved-section"' in text
    assert 'id="saved-list"' in text
    assert 'id="saved-count"' in text
    # Error banner
    assert 'id="error-banner"' in text
    assert 'id="error-dismiss"' in text
    # Empty-state hint
    assert 'id="hint-section"' in text
    # Refresh button (manual reload of saved items)
    assert 'id="refresh-btn"' in text
    # Templates the JS clones
    assert 'id="tpl-saved-item"' in text
    assert 'id="tpl-output-row"' in text


def test_index_html_no_dead_search_box() -> None:
    """The server-side search box is dead (anti-bot blocks it) and was removed.
    Capture happens via the browser extension's Save button now."""
    text = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="search-form"' not in text, "dead search box should be removed"
    assert 'id="search-input"' not in text, "dead search input should be removed"
    assert 'id="results-section"' not in text, "dead results section should be removed"


def test_app_js_exists_and_uses_iife() -> None:
    p = STATIC_DIR / "app.js"
    assert p.exists(), f"missing {p}"
    text = p.read_text(encoding="utf-8")
    assert "(function ()" in text or "(function() {" in text
    assert '"use strict";' in text
    assert "window.ShopeeTH" in text


def test_app_js_calls_documented_endpoints() -> None:
    """Static check that the surviving routes are referenced from the JS.
    (POST /api/search is dead — removed with the search box.)"""
    text = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    # api.listSaved → GET /api/saved
    assert '"/api/saved"' in text and "method: \"GET\"" in text
    # DELETE
    assert 'method: "DELETE"' in text
    # Caption / clip-prompt
    assert "/caption" in text
    assert "/clip-prompt" in text
    # Outputs
    assert "/outputs" in text


def test_app_js_has_auto_refresh_for_captured_items() -> None:
    """The view polls for newly-captured items so they appear without a reload."""
    text = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "refreshSaved" in text
    assert "setInterval" in text or "POLL_INTERVAL_MS" in text


def test_app_js_renders_error_banner_with_server_message() -> None:
    text = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "showError" in text
    assert "detail.message" in text
    assert "guidance" in text


def test_styles_css_exists_and_has_root_vars() -> None:
    p = STATIC_DIR / "styles.css"
    assert p.exists(), f"missing {p}"
    text = p.read_text(encoding="utf-8")
    assert ":root" in text
    assert "--primary" in text
    assert "--danger" in text
    # The redesign uses the Shopee-orange token for commission badges.
    assert "--shopee" in text


def test_styles_css_is_vanilla_no_framework_imports() -> None:
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
