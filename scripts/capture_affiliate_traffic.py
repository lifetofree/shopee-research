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

import gzip
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Request, Response, sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
DUMP_PATH = REPO_ROOT / "docs" / "research" / "affiliate-observed-traffic.json"

AFFILIATE_URL = "https://affiliate.shopee.co.th/"
AFFILIATE_HOST = "affiliate.shopee.co.th"

# A realistic desktop Chrome context. Shopee's affiliate portal walls off
# automation-fingerprinted browsers with a "Loading Issue" page (research §3.5),
# so we launch with the automation flag hidden and a believable UA/viewport/
# locale. This is the difference between the portal serving real data and
# serving the soft "try again" error page.
DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
STEALTH_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]

# --- Real-Chrome attach path -------------------------------------------------
# Playwright's bundled Chromium is fingerprinted by Shopee's anti-bot and
# redirected to a `scene=crawler_item` captcha wall. To get past it, we launch
# the system's genuine Google Chrome with a remote-debugging port and connect
# Playwright to it as a passive listener only. Real Chrome = real fingerprint;
# Playwright drives it over CDP but the page sees an unmodified Chrome.
DEBUG_PORT = 9222
# macOS default Chrome location; overridable for Linux/Windows.
SYSTEM_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]

CAPTURE_WINDOW_SECONDS = 60.0
# Override the default window when a run needs longer (e.g. an interactive
# login + captcha). `<= 0` means "wait until a stop file appears, no timeout".
CAPTURE_WINDOW_ENV = "SHOPEE_TH_CAPTURE_TIMEOUT"
# A run ends when this file appears (created by the operator), when the browser
# window is closed, or when the timeout elapses — whichever comes first. Using a
# file signal instead of stdin keeps the script robust to being launched with a
# detached/closed stdin (which would otherwise end the capture instantly).
STOP_FILE = REPO_ROOT / ".capture-stop"
MAX_BODY_BYTES = 4096


def _capture_window() -> float:
    """Resolve the capture-window seconds from env, falling back to the default."""
    raw = os.environ.get(CAPTURE_WINDOW_ENV)
    if raw is None or raw == "":
        return CAPTURE_WINDOW_SECONDS
    return float(raw)


def _touch(path: Path) -> None:
    """Create `path` as an empty signal file (best-effort, never raises)."""
    try:
        path.touch()
    except OSError:
        pass


def _find_system_chrome() -> str | None:
    """Locate the system Google Chrome binary, if installed. Pure/testable."""
    import os

    for candidate in SYSTEM_CHROME_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


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


def _read_response_body(response: Response) -> str | None:
    """Read a response body as text, transparently decompressing gzip.

    `response.text()` returns an empty string for bodies that were already
    consumed or delivered with a content-encoding the listener can't re-decode,
    so we fetch raw bytes and decompress ourselves when needed. Returns `None`
    for genuinely non-text bodies (images, fonts, etc.).
    """
    try:
        raw = response.body()
    except Exception:  # noqa: BLE001 - non-text / detached bodies aren't useful here
        return None
    if not raw:
        return None
    encoding = ""
    for header, value in response.headers.items():
        if header.lower() == "content-encoding":
            encoding = value.lower()
            break
    try:
        if "gzip" in encoding:
            raw = gzip.decompress(raw)
        elif "br" in encoding:
            try:
                import brotli  # type: ignore[import-untyped]
            except ImportError:
                # brotli optional; leave compressed bytes to decode with errors replaced
                pass
            else:
                raw = brotli.decompress(raw)
        return raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - never let body decoding break the capture
        return None


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


def _wait_for_stop_or_timeout(prompt: str, timeout_seconds: float, stop_file: Path) -> None:
    """Block until the stop file appears or `timeout_seconds` elapse.

    `timeout_seconds <= 0` disables the timeout (wait for the stop file only).
    Polls every 0.5 s. Never raises — running out the clock is a normal stop
    condition here (per the ticket: "60s of typing"), not a failure.
    """
    print(prompt, flush=True)
    deadline = None if timeout_seconds <= 0 else time.monotonic() + timeout_seconds
    while True:
        if stop_file.exists():
            try:
                stop_file.unlink()
            except OSError:
                pass
            print("Stop file detected — ending capture.", flush=True)
            return
        if deadline is not None and time.monotonic() >= deadline:
            print(f"Capture window ({timeout_seconds:.0f}s) elapsed — ending capture.", flush=True)
            return
        time.sleep(0.5)


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
            body = _read_response_body(response)
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
    """Launch real Chrome (debug port) + connect Playwright as a passive listener.

    Why not `playwright.chromium.launch()`? Shopee's anti-bot fingerprints
    Playwright's bundled Chromium and walls it off with a `scene=crawler_item`
    captcha (verified empirically). The system's genuine Google Chrome has a
    real fingerprint; we drive it over CDP purely to attach network listeners.
    """
    import subprocess

    entries: list[dict] = []
    window = _capture_window()

    chrome_path = _find_system_chrome()
    if chrome_path is None:
        print(
            "Could not find the system Google Chrome. Install Chrome, or add its path "
            "to SYSTEM_CHROME_CANDIDATES in this script.",
            file=sys.stderr,
        )
        return entries

    # Fresh, throwaway user-data-dir so we never disturb the user's real profile.
    profile_dir = REPO_ROOT / ".chrome-capture-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    chrome_proc = subprocess.Popen(
        [
            chrome_path,
            f"--remote-debugging-port={DEBUG_PORT}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            AFFILIATE_URL,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    browser = None
    try:
        with sync_playwright() as playwright:
            # Connect to the already-running real Chrome over CDP.
            for _ in range(20):
                try:
                    browser = playwright.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
                    break
                except Exception:  # noqa: BLE001 - Chrome may need a moment to open the port
                    time.sleep(0.5)
            if browser is None:
                print(
                    f"Could not connect to Chrome on port {DEBUG_PORT} after 10s. "
                    "Is another Chrome instance using that port?",
                    file=sys.stderr,
                )
                return entries

            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page() if not context.pages else context.pages[0]
            context.on("close", lambda *_: _touch(STOP_FILE))
            try:
                _attach_listeners(page, entries)
                # If the fresh profile didn't auto-navigate (it usually does via the
                # argv URL), nudge it; don't block on `load` — see note below.
                try:
                    if "affiliate.shopee.co.th" not in page.url:
                        page.goto(AFFILIATE_URL, wait_until="domcontentloaded", timeout=60000)
                except Exception as exc:  # noqa: BLE001 - navigation flakiness shouldn't end the run
                    print(f"Initial navigation was flaky ({type(exc).__name__}); the window is "
                          f"still open — reload the page in Chrome if needed.", flush=True)
                timeout_desc = (
                    "no timeout — create .capture-stop when done"
                    if window <= 0
                    else f"{window:.0f}s"
                )
                _wait_for_stop_or_timeout(
                    "\nReal Chrome is open on affiliate.shopee.co.th. Log in, navigate to the "
                    "search/offers page, and run a real search (e.g. 'iphone 15 case').\n"
                    f"Capture ends when you close Chrome, when {STOP_FILE.name} appears, "
                    f"or after {timeout_desc} — whichever first.",
                    window,
                    STOP_FILE,
                )
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    finally:
        chrome_proc.terminate()
        try:
            chrome_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chrome_proc.kill()
    return entries


def main() -> int:
    # Clear any stale stop file so this run doesn't end instantly.
    if STOP_FILE.exists():
        try:
            STOP_FILE.unlink()
        except OSError:
            pass
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
