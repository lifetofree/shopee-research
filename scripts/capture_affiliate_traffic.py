#!/usr/bin/env python3
"""One-shot empirical capture of affiliate.shopee.co.th's hidden API traffic.

Run via `make capture-affiliate-traffic`. Opens a headed Chromium, lets the
user log in and drive a real search in the affiliate portal, and dumps every
request/response to/from `affiliate.shopee.co.th` to
`docs/research/affiliate-observed-traffic.json`.

This is the bridge from `docs/research/data-surfaces.md`'s Surface B
*inference* (the `productOfferV2`-shaped GraphQL guess in
`services/search.py`) to a *confirmed* contract: exact endpoint URLs, request
bodies, and response shapes. Until this dump exists and has been reviewed,
the affiliate leg in `services/search.py` stays best-effort scaffolding.

Unlike `refresh_cookie.py`, the user drives the search itself inside the
browser — the portal's search UI (selectors, page URL, DOM structure) is
explicitly unconfirmed per the research write-up, so there's nothing for
this script to click through on the user's behalf. Its job is purely to
listen and record.
"""

from __future__ import annotations

import json
import select
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Request, Response, sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
DUMP_PATH = REPO_ROOT / "docs" / "research" / "affiliate-observed-traffic.json"

AFFILIATE_URL = "https://affiliate.shopee.co.th/"
AFFILIATE_HOST = "affiliate.shopee.co.th"
CAPTURE_WINDOW_SECONDS = 60.0
MAX_BODY_BYTES = 4096


def _is_target_host(url: str, host: str = AFFILIATE_HOST) -> bool:
    """True if `url`'s host matches (or is a subdomain of) `host`.

    Pure/testable: no network, no Playwright objects.
    """
    netloc = urlparse(url).netloc.split(":")[0].lower()
    return netloc == host or netloc.endswith(f".{host}")


def _truncate_body(text: str, max_bytes: int = MAX_BODY_BYTES) -> tuple[str, bool]:
    """Truncate `text` to `max_bytes` (UTF-8 byte-safe). Returns (text, was_truncated)."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def _make_entry(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    post_data: str | None,
    status: int | None,
    response_headers: dict[str, str] | None,
    response_body: str | None,
) -> dict:
    """Build one dump entry in the ticket's documented shape. Pure/testable."""
    body_truncated = ""
    was_truncated = False
    if response_body is not None:
        body_truncated, was_truncated = _truncate_body(response_body)
    return {
        "method": method,
        "url": url,
        "headers": headers,
        "post_data": post_data,
        "status": status,
        "response_headers": response_headers,
        "response_body_truncated": body_truncated,
        "truncated": was_truncated,
    }


def _wait_for_enter_or_timeout(prompt: str, timeout_seconds: float) -> None:
    """Block until Enter or `timeout_seconds` elapse — whichever first. Never raises.

    Unlike `refresh_cookie.py`'s login gate, running out the clock here is a
    normal stop condition (per the ticket: "60s of typing"), not a failure.
    """
    print(prompt, flush=True)
    select.select([sys.stdin], [], [], timeout_seconds)


def _attach_listeners(page: Page, entries: list[dict]) -> None:
    """Wire request/response listeners that append matching traffic to `entries`."""
    pending_requests: dict[Request, dict] = {}

    def on_request(request: Request) -> None:
        if not _is_target_host(request.url):
            return
        pending_requests[request] = {
            "method": request.method,
            "url": request.url,
            "headers": dict(request.headers),
            "post_data": request.post_data,
        }

    def on_response(response: Response) -> None:
        request = response.request
        pending = pending_requests.pop(request, None)
        if pending is None:
            if not _is_target_host(response.url):
                return
            pending = {
                "method": request.method,
                "url": response.url,
                "headers": dict(request.headers),
                "post_data": request.post_data,
            }
        try:
            body = response.text()
        except Exception:  # noqa: BLE001 - non-text bodies (images, etc.) aren't useful here
            body = None
        entries.append(
            _make_entry(
                method=pending["method"],
                url=pending["url"],
                headers=pending["headers"],
                post_data=pending["post_data"],
                status=response.status,
                response_headers=dict(response.headers),
                response_body=body,
            )
        )

    page.on("request", on_request)
    page.on("response", on_response)


def run() -> list[dict]:
    entries: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        try:
            _attach_listeners(page, entries)
            page.goto(AFFILIATE_URL)
            _wait_for_enter_or_timeout(
                "\naffiliate.shopee.co.th is open. Log in if needed, navigate to the "
                "search/offers page, and run a real search (e.g. 'iphone 15 case').\n"
                f"Press Enter here when done, or just wait — capture stops automatically "
                f"after {CAPTURE_WINDOW_SECONDS:.0f}s either way.",
                CAPTURE_WINDOW_SECONDS,
            )
        finally:
            context.close()
            browser.close()
    return entries


def main() -> int:
    entries = run()
    DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
    DUMP_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
    print(f"\nCaptured {len(entries)} affiliate.shopee.co.th request(s) -> {DUMP_PATH}")
    if len(entries) < 3:
        print(
            "Fewer than 3 requests captured — the acceptance bar in the ticket wants "
            "≥3 distinct request types. Re-run and interact with the portal a bit more "
            "before the window closes.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
