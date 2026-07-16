"""Unit tests for the pure helpers in `scripts/refresh_cookie.py`.

The script's core loop (launch Chromium, wait for an interactive login) isn't
unit-testable without a real browser and a human — this only covers the
pieces that don't touch Playwright or the filesystem: cookie-string joining
and the `.env` upsert.
"""

from __future__ import annotations

from refresh_cookie import _cookie_header, _upsert_env_vars


class _FakeContext:
    """Duck-types the slice of `BrowserContext` that `_cookie_header` uses."""

    def __init__(self, cookies: list[dict]) -> None:
        self._cookies = cookies

    def cookies(self, url: str) -> list[dict]:  # noqa: ARG002 - matches Playwright's signature
        return self._cookies


def test_cookie_header_joins_name_value_pairs() -> None:
    context = _FakeContext(
        [
            {"name": "SPC_F", "value": "abc123"},
            {"name": "SPC_U", "value": "42"},
        ]
    )
    assert _cookie_header(context, "https://shopee.co.th/") == "SPC_F=abc123; SPC_U=42"


def test_cookie_header_empty_when_no_cookies() -> None:
    assert _cookie_header(_FakeContext([]), "https://shopee.co.th/") == ""


def test_upsert_env_vars_replaces_existing_key_in_place() -> None:
    existing = "SHOPEE_TH_SESSION_COOKIE=old\nSHOPEE_TH_GENERATOR=stub\n"
    updated = _upsert_env_vars(existing, {"SHOPEE_TH_SESSION_COOKIE": "new"})
    lines = updated.splitlines()
    assert lines[0] == "SHOPEE_TH_SESSION_COOKIE=new"
    assert lines[1] == "SHOPEE_TH_GENERATOR=stub"


def test_upsert_env_vars_appends_missing_key() -> None:
    updated = _upsert_env_vars("SHOPEE_TH_GENERATOR=stub\n", {"SHOPEE_TH_SESSION_COOKIE": "new"})
    assert "SHOPEE_TH_GENERATOR=stub" in updated
    assert "SHOPEE_TH_SESSION_COOKIE=new" in updated


def test_upsert_env_vars_preserves_comments_and_blank_lines() -> None:
    existing = "# a comment\n\nSHOPEE_TH_SESSION_COOKIE=old\n"
    updated = _upsert_env_vars(existing, {"SHOPEE_TH_SESSION_COOKIE": "new"})
    assert "# a comment" in updated.splitlines()
    assert "SHOPEE_TH_SESSION_COOKIE=new" in updated


def test_upsert_env_vars_is_idempotent_on_rerun() -> None:
    existing = "SHOPEE_TH_SESSION_COOKIE=old\nSHOPEE_TH_AFFILIATE_ID=\n"
    values = {
        "SHOPEE_TH_SESSION_COOKIE": "new",
        "SHOPEE_TH_AFFILIATE_COOKIE": "aff",
        "SHOPEE_TH_AFFILIATE_ID": "",
    }
    once = _upsert_env_vars(existing, values)
    twice = _upsert_env_vars(once, values)
    assert once == twice


def test_upsert_env_vars_from_empty_text() -> None:
    updated = _upsert_env_vars("", {"SHOPEE_TH_SESSION_COOKIE": "new"})
    assert updated == "SHOPEE_TH_SESSION_COOKIE=new\n"
