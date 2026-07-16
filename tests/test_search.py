"""Unit tests for `services.search` driven by `NoopTransport`.

Surface A only (see the module docstring in `services/search.py` for why
Surface B was dropped — it's confirmed non-server-side-replayable).

Coverage targets:
- happy path: Surface A returns N items, `commission` always `None`
- empty result: Surface A returns `items: []` → `search()` returns `[]`
- 90309999 → SearchError with guidance (no retry)
- transient error_msg → single retry succeeds
- 5xx → SearchError after one retry
- timeout → SearchError after one retry
- `limit` clamping
- empty query → `[]` without any HTTP call
- missing cookie → SearchError (config issue, not upstream)
"""

from __future__ import annotations

import asyncio

import pytest

from shopee_th.services.search import (
    COOKIE_BINDING_ERROR,
    MAX_LIMIT,
    SearchError,
    search,
)
from shopee_th.services.transport import NoopTransport, TransportResponse


# --- Fixtures -------------------------------------------------------------


def _surface_a_item(
    itemid: str | int = 111,
    *,
    image: str = "abc123",
    price_micros: int = 12_900_000,  # ฿129.00
    sold: int = 1234,
    title: str = "iPhone 15 case",
) -> dict:
    """Build a minimal Surface A `items[i]` row."""
    return {
        "item_basic": {
            "itemid": str(itemid),
            "image": image,
            "price": price_micros,
            "price_min": price_micros,
            "historical_sold": sold,
            "name": title,
        }
    }


def _surface_a_ok(*items: dict) -> TransportResponse:
    return TransportResponse(status=200, json={"items": list(items), "total_count": len(items)})


# --- Tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_parses_image_price_sold() -> None:
    transport = NoopTransport(default_response=_surface_a_ok(_surface_a_item(111)))
    items = await search(
        transport,
        query="iphone 15 case",
        session_cookie="SPC=abc",
    )
    assert len(items) == 1
    item = items[0]
    assert item.source_id == "111"
    assert item.image == "https://cf.shopee.co.th/file/abc123"
    assert item.price == pytest.approx(129.0)  # 12_900_000 / 100_000
    assert item.sold == 1234
    assert item.title == "iPhone 15 case"
    assert item.commission is None  # Surface A never sets this
    assert "item_basic" in item.raw


@pytest.mark.asyncio
async def test_empty_query_returns_empty_without_calling_transport() -> None:
    transport = NoopTransport(default_response=_surface_a_ok())
    items = await search(transport, query="", session_cookie="SPC=abc")
    assert items == []
    assert transport.calls == []  # no HTTP at all

    items = await search(transport, query="   ", session_cookie="SPC=abc")
    assert items == []
    assert transport.calls == []


@pytest.mark.asyncio
async def test_missing_session_cookie_raises_search_error() -> None:
    transport = NoopTransport()
    with pytest.raises(SearchError) as exc_info:
        await search(transport, query="anything", session_cookie="")
    assert exc_info.value.guidance and "refresh-cookie" in exc_info.value.guidance
    assert transport.calls == []  # no HTTP at all


@pytest.mark.asyncio
async def test_empty_result_returns_empty_list() -> None:
    transport = NoopTransport(
        default_response=TransportResponse(status=200, json={"items": []}),
    )
    items = await search(transport, query="no-such-product", session_cookie="SPC=abc")
    assert items == []


@pytest.mark.asyncio
async def test_90309999_raises_search_error_without_retry() -> None:
    transport = NoopTransport(
        default_response=TransportResponse(
            status=200,
            json={
                "items": [],
                "error": COOKIE_BINDING_ERROR,
                "error_msg": "Need login",
            },
        )
    )
    with pytest.raises(SearchError) as exc_info:
        await search(transport, query="iphone", session_cookie="bad-cookie")
    err = exc_info.value
    assert err.code == COOKIE_BINDING_ERROR
    assert err.guidance and "refresh-cookie" in err.guidance
    # No retry — one call only.
    assert sum(1 for c in transport.calls if c["method"] == "GET") == 1


@pytest.mark.asyncio
async def test_transient_error_msg_retries_once_then_returns_data() -> None:
    transient = TransportResponse(
        status=200,
        json={"items": [], "error_msg": "Please retry"},
    )
    ok = _surface_a_ok(_surface_a_item(111))
    transport = NoopTransport()
    transport.push_many([transient, ok])

    items = await search(transport, query="iphone", session_cookie="SPC=abc")
    assert len(items) == 1
    assert items[0].source_id == "111"
    # Two GETs: the failing one + the retry.
    assert sum(1 for c in transport.calls if c["method"] == "GET") == 2


@pytest.mark.asyncio
async def test_5xx_retries_once_then_raises() -> None:
    transport = NoopTransport()
    transport.push_many(
        [
            TransportResponse(status=502, json={}),
            TransportResponse(status=502, json={}),
        ]
    )
    with pytest.raises(SearchError) as exc_info:
        await search(transport, query="iphone", session_cookie="SPC=abc")
    assert "502" in str(exc_info.value)
    assert sum(1 for c in transport.calls if c["method"] == "GET") == 2


@pytest.mark.asyncio
async def test_timeout_retries_once_then_raises() -> None:
    class _TimeoutTransport(NoopTransport):
        async def get(self, *args, **kwargs):  # type: ignore[override]
            self.calls.append({"method": "GET", "url": args[0] if args else ""})
            raise asyncio.TimeoutError("upstream timeout")

    transport = _TimeoutTransport()
    with pytest.raises(SearchError) as exc_info:
        await search(transport, query="iphone", session_cookie="SPC=abc")
    assert "Network error" in str(exc_info.value) or "timeout" in str(exc_info.value).lower()
    assert sum(1 for c in transport.calls if c["method"] == "GET") == 2


@pytest.mark.asyncio
async def test_limit_clamped_to_max() -> None:
    transport = NoopTransport(default_response=_surface_a_ok())
    await search(transport, query="iphone", session_cookie="SPC=abc", limit=999)
    get_call = next(c for c in transport.calls if c["method"] == "GET")
    assert get_call["params"]["limit"] == MAX_LIMIT


@pytest.mark.asyncio
async def test_limit_clamped_to_min() -> None:
    transport = NoopTransport(default_response=_surface_a_ok())
    await search(transport, query="iphone", session_cookie="SPC=abc", limit=0)
    get_call = next(c for c in transport.calls if c["method"] == "GET")
    assert get_call["params"]["limit"] == 1


@pytest.mark.asyncio
async def test_surface_a_sends_required_headers() -> None:
    transport = NoopTransport(default_response=_surface_a_ok(_surface_a_item(111)))
    await search(transport, query="iphone", session_cookie="SPC=abc; foo=bar")
    get_call = next(c for c in transport.calls if c["method"] == "GET")
    headers = get_call["headers"]
    assert headers["x-api-source"] == "pc"
    assert headers["af-ac-enc-dat"] == "null"
    assert headers["cookie"] == "SPC=abc; foo=bar"
    assert headers["referer"] == "https://shopee.co.th/"
    assert "User-Agent" in headers


@pytest.mark.asyncio
async def test_search_returns_list_not_generator_on_empty() -> None:
    transport = NoopTransport(
        default_response=TransportResponse(status=200, json={"items": []})
    )
    result = await search(transport, query="x", session_cookie="SPC=abc")
    assert isinstance(result, list)
    assert result == []


@pytest.mark.asyncio
async def test_price_falls_back_to_price_min_when_price_is_zero() -> None:
    raw = {
        "item_basic": {
            "itemid": "999",
            "image": "img",
            "price": 0,
            "price_min": 590_000,  # ฿5.90 (IP-tampered fallback)
            "historical_sold": 10,
        }
    }
    transport = NoopTransport(
        default_response=TransportResponse(status=200, json={"items": [raw]})
    )
    items = await search(transport, query="x", session_cookie="SPC=abc")
    # Python `round(5.9) == 6` (banker's rounding rounds half-to-even, but
    # 5.9 is unambiguously > 5.5). The point of the test is the fallback
    # path, not the rounding rule, so accept the rounded value.
    assert items[0].price == pytest.approx(6.0)  # round(590_000 / 100_000)
