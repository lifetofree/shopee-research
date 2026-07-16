"""Search service: two-leg merge of Shopee storefront + affiliate-portal data.

Surface A (`shopee.co.th/api/v4/search/search_items`) is closed research and
supplies image/price/sold. Surface B (`affiliate.shopee.co.th`) is still
empirical (see docs/research/data-surfaces.md §3) and supplies commission on
a best-effort basis until `capture-affiliate-portal-traffic` lands a
confirmed contract.

No FastAPI / app-config imports here — this module is library-importable and
depends only on the injected `Transport`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from shopee_th.models.domain import Item
from shopee_th.services.transport import Transport

SURFACE_A_URL = "https://shopee.co.th/api/v4/search/search_items"
SURFACE_B_URL = "https://affiliate.shopee.co.th/graphql"
DEFAULT_REFERER = "https://shopee.co.th/"
AFFILIATE_REFERER = "https://affiliate.shopee.co.th/"
CF_IMAGE_PREFIX = "https://cf.shopee.co.th/file/"
COOKIE_BINDING_ERROR_CODE = 90309999
MAX_LIMIT = 20
RETRY_BACKOFF_SECONDS = 0.05

# Inferred GraphQL shape (research §3.3) — unconfirmed until the capture ticket lands.
AFFILIATE_GRAPHQL_QUERY = """
query ProductOfferSearch($keyword: String!, $limit: Int!) {
  productOfferV2(keyword: $keyword, limit: $limit) {
    nodes {
      itemId
      commissionRate
      sellerCommissionRate
      shopeeCommissionRate
      commission
      sales
      priceMin
      priceMax
      productName
      shopName
      imageUrl
    }
  }
}
"""


class SearchError(Exception):
    """Raised for upstream Shopee failures. Carries the offending URL and error code, if any."""

    def __init__(self, message: str, *, url: str | None = None, code: int | str | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.code = code
        self.is_timeout = False


class _TransientShopeeError(Exception):
    """Internal: a 200 response carrying a retriable `error`/`error_msg` pair."""

    def __init__(self, message: str, *, code: int | str | None = None) -> None:
        super().__init__(message)
        self.code = code


async def search(
    query: str,
    limit: int = 20,
    *,
    transport: Transport,
    session_cookie: str,
    user_agent: str,
    affiliate_cookie: str | None = None,
    affiliate_leg: bool = True,
    offset: int = 0,
) -> list[Item]:
    """Search Shopee TH, merging in commission from the affiliate leg when possible."""
    capped_limit = max(1, min(limit, MAX_LIMIT))

    data = await _fetch_surface_a(
        transport,
        query=query,
        limit=capped_limit,
        offset=offset,
        session_cookie=session_cookie,
        user_agent=user_agent,
    )
    raw_items = data.get("items") or []
    items = [_parse_item(entry) for entry in raw_items]

    if affiliate_leg and items:
        commissions = await _try_fetch_commissions(
            transport,
            query=query,
            limit=capped_limit,
            affiliate_cookie=affiliate_cookie,
            user_agent=user_agent,
        )
        for item in items:
            item_id = str(item.raw.get("itemid"))
            if item_id in commissions:
                item.commission = commissions[item_id]

    return items


async def _fetch_surface_a(
    transport: Transport,
    *,
    query: str,
    limit: int,
    offset: int,
    session_cookie: str,
    user_agent: str,
) -> dict[str, Any]:
    headers = {
        "User-Agent": user_agent,
        "cookie": session_cookie,
        "referer": DEFAULT_REFERER,
        "x-api-source": "pc",
        "af-ac-enc-dat": "null",
    }
    params: dict[str, Any] = {
        "by": "relevancy",
        "limit": limit,
        "keyword": query,
        "newest": offset,
        "order": "desc",
        "page_type": "search",
        "scenario": "PAGE_SEARCH",
        "version": "2",
    }

    async def attempt() -> dict[str, Any]:
        body = await transport.get(SURFACE_A_URL, headers=headers, params=params)
        error_code = body.get("error")
        if error_code:
            if error_code == COOKIE_BINDING_ERROR_CODE:
                raise SearchError(
                    "Shopee rejected the cookie (error 90309999) — the cookie is bound to a "
                    "different browser fingerprint. Re-run `make refresh-cookie`.",
                    url=SURFACE_A_URL,
                    code=error_code,
                )
            raise _TransientShopeeError(
                body.get("error_msg", "transient upstream error"), code=error_code
            )
        return body

    return await _call_with_retry(attempt, url=SURFACE_A_URL)


async def _try_fetch_commissions(
    transport: Transport,
    *,
    query: str,
    limit: int,
    affiliate_cookie: str | None,
    user_agent: str,
) -> dict[str, float]:
    """Best-effort Surface B call. Any failure (including NotImplementedError) yields `{}`."""
    try:
        return await _fetch_surface_b(
            transport,
            query=query,
            limit=limit,
            affiliate_cookie=affiliate_cookie,
            user_agent=user_agent,
        )
    except Exception:
        return {}


async def _fetch_surface_b(
    transport: Transport,
    *,
    query: str,
    limit: int,
    affiliate_cookie: str | None,
    user_agent: str,
) -> dict[str, float]:
    if not affiliate_cookie:
        raise NotImplementedError("Surface B requires SHOPEE_TH_AFFILIATE_COOKIE")

    headers = {
        "User-Agent": user_agent,
        "cookie": affiliate_cookie,
        "referer": AFFILIATE_REFERER,
        "content-type": "application/json",
    }
    body = {
        "query": AFFILIATE_GRAPHQL_QUERY,
        "variables": {"keyword": query, "limit": limit},
    }

    response = await transport.post(SURFACE_B_URL, headers=headers, json=body)
    nodes = ((response.get("data") or {}).get("productOfferV2") or {}).get("nodes") or []

    commissions: dict[str, float] = {}
    for node in nodes:
        item_id = node.get("itemId")
        commission = node.get("commission")
        if item_id is not None and commission is not None:
            commissions[str(item_id)] = commission
    return commissions


async def _call_with_retry(
    make_attempt: Callable[[], Awaitable[dict[str, Any]]], *, url: str
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt_number in range(2):
        try:
            return await make_attempt()
        except SearchError:
            raise
        except Exception as exc:  # noqa: BLE001 - transport/transient errors are the retry target
            last_exc = exc
            if attempt_number == 0:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
                continue

    message = str(last_exc) or type(last_exc).__name__
    err = SearchError(f"Surface A request failed: {message}", url=url, code=getattr(last_exc, "code", None))
    err.is_timeout = "timeout" in type(last_exc).__name__.lower()
    raise err from last_exc


def _parse_item(entry: dict[str, Any]) -> Item:
    basic = entry.get("item_basic", entry)
    itemid = basic.get("itemid")
    shopid = basic.get("shopid")

    image_id = basic.get("image")
    image = f"{CF_IMAGE_PREFIX}{image_id}" if image_id else None

    return Item(
        source_id=f"{shopid}.{itemid}",
        title=basic.get("name") or "",
        image=image,
        price=_extract_price(basic),
        sold=basic.get("historical_sold"),
        commission=None,
        raw=basic,
    )


def _extract_price(basic: dict[str, Any]) -> float | None:
    # `price` is occasionally IP/locale-tampered (research §2.5); fall back to price_min.
    value = basic.get("price") or basic.get("price_min")
    if value is None:
        return None
    return round(value / 100000, 2)
