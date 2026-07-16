#!/usr/bin/env python3
"""Interactive Playwright cookie-refresh helper. Run via `make refresh-cookie`.

Opens a single headed Chromium, lets the user log in to shopee.co.th and
affiliate.shopee.co.th, then persists both cookie jars to `.env` so the app
can replay them (Surface A / Surface B auth per
docs/research/data-surfaces.md).

Shopee binds session cookies to the browser fingerprint that produced them
(the `SPC_*` values) — cookies harvested from any other browser/process fail
with `error: 90309999`. This script must be the one Chromium session that
both logs in and is read back from immediately after, in the same run.
"""

from __future__ import annotations

import re
import select
import sys
from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"

SHOPEE_URL = "https://shopee.co.th/"
AFFILIATE_URL = "https://affiliate.shopee.co.th/"
LOGIN_TIMEOUT_SECONDS = 300.0


class RefreshCookieError(Exception):
    """Raised on timeout or another unrecoverable failure. `main()` exits non-zero on this."""


def _cookie_header(context: BrowserContext, url: str) -> str:
    """`; `-joined `name=value` cookie string for the given origin.

    `context.cookies(url)` is Playwright's own origin-scoped filter (matches
    domain/path/secure), so this returns exactly the cookies that origin's
    server would see — no manual domain filtering needed.
    """
    cookies = context.cookies(url)
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def _wait_for_enter(prompt: str, timeout_seconds: float) -> None:
    """Block on a keypress, guarded by a timeout so a hung/abandoned session exits cleanly."""
    print(prompt, flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
    if not ready:
        raise RefreshCookieError(f"Timed out after {timeout_seconds:.0f}s waiting for confirmation.")
    sys.stdin.readline()


def _upsert_env_vars(existing_text: str, values: dict[str, str]) -> str:
    """Set `KEY=value` for each key in `values` in `existing_text`.

    Replaces an existing `KEY=...` line in place; appends keys that aren't
    already present. Every other line (comments, unrelated keys) is preserved
    verbatim, so re-running is idempotent — a rerun with the same values
    produces byte-identical output, and a rerun with new values only touches
    the three cookie lines. Pure string transform: no filesystem access, so
    it's directly unit-testable.
    """
    lines = existing_text.splitlines() if existing_text else []
    remaining = dict(values)
    result: list[str] = []
    for line in lines:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
        key = match.group(1) if match else None
        if key is not None and key in remaining:
            result.append(f"{key}={remaining.pop(key)}")
        else:
            result.append(line)
    for key, value in remaining.items():
        result.append(f"{key}={value}")
    return "\n".join(result) + "\n"


def _load_env_template() -> str:
    """Seed content for `.env`: the existing file, else `.env.example`, else empty."""
    if ENV_PATH.exists():
        return ENV_PATH.read_text()
    if ENV_EXAMPLE_PATH.exists():
        return ENV_EXAMPLE_PATH.read_text()
    return ""


def run() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(SHOPEE_URL)
            _wait_for_enter(
                "\n1/2 — shopee.co.th is open. Log in if you're not already "
                "(skip if you're already signed in), then press Enter here to "
                f"continue (times out after {LOGIN_TIMEOUT_SECONDS:.0f}s)...",
                LOGIN_TIMEOUT_SECONDS,
            )
            session_cookie = _cookie_header(context, SHOPEE_URL)
            if not session_cookie:
                raise RefreshCookieError(f"No cookies captured for {SHOPEE_URL}.")
            # Shopee binds session_cookie to this exact browser's UA (research
            # §2.5) — persist it so the app replays requests with a matching
            # fingerprint instead of a hardcoded default that drifts out of
            # sync with Playwright's bundled Chromium version.
            user_agent = page.evaluate("() => navigator.userAgent")

            page.goto(AFFILIATE_URL)
            _wait_for_enter(
                "\n2/2 — affiliate.shopee.co.th is open. Log in, then press "
                f"Enter here to continue (times out after {LOGIN_TIMEOUT_SECONDS:.0f}s)...",
                LOGIN_TIMEOUT_SECONDS,
            )
            affiliate_cookie = _cookie_header(context, AFFILIATE_URL)
            if not affiliate_cookie:
                raise RefreshCookieError(f"No cookies captured for {AFFILIATE_URL}.")
        finally:
            context.close()
            browser.close()

    updated = _upsert_env_vars(
        _load_env_template(),
        {
            "SHOPEE_TH_SESSION_COOKIE": session_cookie,
            "SHOPEE_TH_AFFILIATE_COOKIE": affiliate_cookie,
            "SHOPEE_TH_AFFILIATE_ID": "",
            "SHOPEE_TH_USER_AGENT": user_agent,
        },
    )
    ENV_PATH.write_text(updated)
    print(f"\nWrote session + affiliate cookies to {ENV_PATH}.")
    print("Restart `make run` / uvicorn to pick up the new cookies.")


def main() -> int:
    try:
        run()
    except RefreshCookieError as exc:
        print(f"refresh-cookie failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nrefresh-cookie aborted by user.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
