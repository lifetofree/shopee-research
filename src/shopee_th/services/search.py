"""Search service: Shopee storefront search (Surface A).

Per the wayfinder map and `implement-search-service` ticket, this originally
scaffolded a two-leg merge with the affiliate portal (Surface B) for
commission. `capture-affiliate-portal-traffic` confirmed the real Surface B
contract (`GET /api/v3/offer/product/list`) but also found it's **not
server-side replayable**: every request needs `x-sap-sec` /
`af-ac-enc-sz-token` / `x-sap-ri`, headers generated per-request by Shopee's
client-side anti-bot SDK running inside a real, non-automated browser. Plain
`httpx` (or an in-page `fetch()` from a CDP-attached browser) gets rejected
with `error: 90309999` even with a valid cookie. See
`docs/research/data-surfaces.md` §3.6 for the full writeup.

**Decision: this app ships on Surface A only.** `Item.commission` is always
`None`. A future architecture (most promising: a browser extension running
in the user's real Chrome, where the anti-bot SDK signs requests naturally)
could add commission back in — that's a different app shape, not a second
`Transport` call, so there's no merge scaffolding here to plug it into.

This module depends only on `Transport` (in `services.transport`) and
Pydantic DTOs. It does **not** import FastAPI, app config, or the DB layer —
making it library-importable and trivially unit-testable via `NoopTransport`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from shopee_th.models.domain import Item, SearchErrorPayload
from shopee_th.services.transport import Transport

SURFACE_A_URL = "https://shopee.co.th/api/v4/search/search_items"

# Linear backoff for the single retry. 0.5s keeps the call wall-clock under
# the typical 10s timeout while still giving upstream a chance to recover.
_RETRY_BACKOFF_SECONDS = 0.5

# `limit` is capped at 20 per ticket (Surface A's hard cap). Anything above
# is clamped silently. Below 1 is also clamped.
MAX_LIMIT = 20
MIN_LIMIT = 1

# Desktop Chrome UA. The ticket specifies "from the same browser that produced
# the cookie" — for v1 we ship a recent stable UA string; the cookie helper
# could later override this per-session.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

# Shopee's hard failure for cookie-binding issues (browser-fingerprint
# mismatch, expired session, etc.). Retrying is pointless — raise SearchError
# with a guidance message so the caller can route the user to
# `make refresh-cookie`.
COOKIE_BINDING_ERROR = 90309999

# Image URL prefix (per the research write-up).
_CF_IMAGE_PREFIX = "https://cf.shopee.co.th/file/"

# Surface A price divisor: prices are in micro-units (THB * 100000).
_PRICE_DIVISOR = 100_000


class SearchError(Exception):
    """Raised when a search cannot complete.

    Attributes:
        url: the offending request URL (when known).
        code: Shopee's `error` field (when known — string or int).
        guidance: a one-line human-readable hint (e.g. "run make refresh-cookie").
    """

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        code: str | int | None = None,
        guidance: str | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.code = code
        self.guidance = guidance


# --- Public entry point ---------------------------------------------------


async def search(
    transport: Transport,
    *,
    query: str,
    limit: int = MAX_LIMIT,
    session_cookie: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[Item]:
    """Search Shopee Affiliate TH for products matching `query`.

    The HTTP layer is responsible for reading `.env` and constructing the
    Transport; this function is pure logic.

    Surface A only — see the module docstring for why. `Item.commission` is
    always `None`.

    Args:
        transport: the Transport to use for Surface A.
        query: the search keyword. Empty / whitespace-only returns `[]`.
        limit: 1..MAX_LIMIT. Clamped silently.
        session_cookie: the `shopee.co.th` cookie string from `.env`.
        user_agent: override the default desktop Chrome UA.

    Returns:
        A list of `Item` rows, newest-first per Shopee's response order. Empty
        if Surface A returned no items or only failed with a non-fatal
        transient error.
    """
    if not query or not query.strip():
        return []
    if not session_cookie:
        # Missing cookie is a config error, not an upstream error.
        raise SearchError(
            "Missing SHOPEE_TH_SESSION_COOKIE; run `make refresh-cookie`.",
            url=SURFACE_A_URL,
            guidance="run `make refresh-cookie`",
        )

    limit = max(MIN_LIMIT, min(int(limit), MAX_LIMIT))

    return await _surface_a_search(
        transport,
        query=query,
        limit=limit,
        session_cookie=session_cookie,
        user_agent=user_agent,
    )


# --- Surface A ------------------------------------------------------------


def _surface_a_headers(*, session_cookie: str, user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "cookie": session_cookie,
        "referer": "https://shopee.co.th/",
        "x-api-source": "pc",
        "af-ac-enc-dat": "null",
    }


def _surface_a_params(*, query: str, limit: int) -> dict[str, Any]:
    return {
        "by": "relevancy",
        "limit": limit,
        "keyword": query,
        "newest": 0,
        "order": "desc",
        "page_type": "search",
        "scenario": "PAGE_SEARCH",
        "version": 2,
    }


async def _surface_a_search(
    transport: Transport,
    *,
    query: str,
    limit: int,
    session_cookie: str,
    user_agent: str,
) -> list[Item]:
    """Call Surface A with one retry on transient errors, return Item rows.

    Retry policy:
    - 200 with `error: COOKIE_BINDING_ERROR` → no retry; raise SearchError
      (the cookie is bad; retrying is pointless).
    - 200 with non-empty `error_msg` (transient Shopee-side blip) → single
      retry with linear backoff.
    - 5xx → single retry.
    - Empty / missing `items` → return `[]` (Shopee uses this shape when
      keyword has no hits).
    - 200 with valid `items` → return parsed items.
    - Anything else (parse error, repeated 5xx, repeated error_msg) → raise
      SearchError.
    """
    headers = _surface_a_headers(session_cookie=session_cookie, user_agent=user_agent)
    params = _surface_a_params(query=query, limit=limit)

    last_error: SearchError | None = None
    for attempt in range(2):
        if attempt > 0:
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
        try:
            resp = await transport.get(SURFACE_A_URL, headers=headers, params=params)
        except (asyncio.TimeoutError, ConnectionError) as e:
            last_error = SearchError(
                f"Network error contacting Shopee: {e}",
                url=SURFACE_A_URL,
            )
            continue  # retry

        # 5xx → retry
        if 500 <= resp.status < 600:
            last_error = SearchError(
                f"Shopee returned HTTP {resp.status}.",
                url=SURFACE_A_URL,
            )
            continue

        # Shopee-side error envelope. Pydantic ignores extra fields so this
        # never raises on a missing key.
        envelope = SearchErrorPayload.model_validate(resp.json)
        if envelope.error is not None:
            # COOKIE_BINDING_ERROR → no retry
            if str(envelope.error) == str(COOKIE_BINDING_ERROR):
                raise SearchError(
                    "Shopee rejected the session cookie "
                    f"(error={envelope.error}, msg={envelope.error_msg!r}). "
                    "Cookies are bound to a browser fingerprint; the helper "
                    "and the searcher must use the same Chromium.",
                    url=SURFACE_A_URL,
                    code=envelope.error,
                    guidance="run `make refresh-cookie` in the same browser you searched in",
                )
            # Other Shopee-side error → retry once
            last_error = SearchError(
                f"Shopee returned error={envelope.error} ({envelope.error_msg!r}).",
                url=SURFACE_A_URL,
                code=envelope.error,
            )
            continue

        # 200 with `error_msg` but no `error` → transient blip → retry
        if envelope.error_msg and not envelope.error:
            last_error = SearchError(
                f"Shopee returned transient error_msg={envelope.error_msg!r}.",
                url=SURFACE_A_URL,
            )
            continue

        # 200 with valid data. Items may be empty/missing → return [].
        items_raw = resp.json.get("items")
        if not items_raw:
            return []
        return [_parse_surface_a_item(it) for it in items_raw if isinstance(it, dict)]

    # Both attempts failed. Raise the last error.
    assert last_error is not None  # loop above always either returns or sets last_error
    raise last_error


def _parse_surface_a_item(raw: dict[str, Any]) -> Item:
    """Map a Surface A `items[i]` row to an `Item` (denormalized + raw)."""
    item_basic = raw.get("item_basic") or {}
    image_id = item_basic.get("image") or ""
    image = f"{_CF_IMAGE_PREFIX}{image_id}" if image_id else ""

    price_micros = item_basic.get("price") or 0
    try:
        price_thb = round(int(price_micros) / _PRICE_DIVISOR)
    except (TypeError, ValueError):
        price_thb = 0
    # Fallback: if `price` looks IP-tampered, use `price_min` (also micros).
    if price_thb <= 0:
        price_min_micros = item_basic.get("price_min") or 0
        try:
            price_thb = round(int(price_min_micros) / _PRICE_DIVISOR)
        except (TypeError, ValueError):
            price_thb = 0

    sold = item_basic.get("historical_sold") or 0
    try:
        sold = int(sold)
    except (TypeError, ValueError):
        sold = 0

    source_id = str(item_basic.get("itemid") or item_basic.get("item_id") or "")

    # Title is promoted (the caption / clip-prompt generator reads it). Shopee
    # puts it at `item_basic.name`; fall back to the empty string so a
    # malformed row doesn't break the merge downstream.
    title = str(item_basic.get("name") or item_basic.get("title") or "")

    return Item(
        source_id=source_id,
        title=title,
        image=image,
        price=float(max(0, price_thb)),
        sold=max(0, sold),
        commission=None,  # Surface A doesn't expose commission; see module docstring
        raw=raw,
    )
