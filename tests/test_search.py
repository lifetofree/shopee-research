"""Unit tests for the search service, driven entirely by NoopTransport."""

from __future__ import annotations

import pytest

from shopee_th.services.search import SearchError, search
from shopee_th.services.transport import NoopTransport

UA = "Mozilla/5.0 (Test) Chrome/126.0.0.0 Safari/537.36"


def _surface_a_item(itemid: int, shopid: int = 1, price: int = 129000000, sold: int = 10) -> dict:
    return {
        "item_basic": {
            "itemid": itemid,
            "shopid": shopid,
            "name": f"Product {itemid}",
            "image": f"abc{itemid}",
            "price": price,
            "price_min": price,
            "historical_sold": sold,
        }
    }


def _surface_a_response(*itemids: int) -> dict:
    return {"items": [_surface_a_item(i) for i in itemids]}


def _surface_b_response(commissions: dict[int, float]) -> dict:
    return {
        "data": {
            "productOfferV2": {
                "nodes": [
                    {"itemId": item_id, "commission": commission}
                    for item_id, commission in commissions.items()
                ]
            }
        }
    }


async def test_search_happy_path_no_affiliate_leg() -> None:
    transport = NoopTransport(get_responses=[_surface_a_response(1, 2, 3)])

    items = await search(
        "iphone case",
        transport=transport,
        session_cookie="cookie",
        user_agent=UA,
        affiliate_leg=False,
    )

    assert [item.source_id for item in items] == ["1.1", "1.2", "1.3"]
    assert all(item.price == 1290.0 for item in items)
    assert all(item.sold == 10 for item in items)
    assert all(item.commission is None for item in items)
    assert items[0].image == "https://cf.shopee.co.th/file/abc1"


async def test_search_empty_result_returns_empty_list() -> None:
    transport = NoopTransport(get_responses=[{"items": []}])

    items = await search(
        "no such product",
        transport=transport,
        session_cookie="cookie",
        user_agent=UA,
    )

    assert items == []


async def test_search_two_leg_fusion_fills_subset_of_commissions() -> None:
    transport = NoopTransport(
        get_responses=[_surface_a_response(1, 2, 3)],
        post_responses=[_surface_b_response({1: 0.06, 3: 0.08})],
    )

    items = await search(
        "iphone case",
        transport=transport,
        session_cookie="cookie",
        affiliate_cookie="affiliate-cookie",
        user_agent=UA,
    )

    by_id = {item.source_id: item.commission for item in items}
    assert by_id["1.1"] == 0.06
    assert by_id["1.2"] is None
    assert by_id["1.3"] == 0.08


async def test_search_surface_b_unavailable_still_returns_surface_a_rows() -> None:
    transport = NoopTransport(get_responses=[_surface_a_response(1, 2)])

    items = await search(
        "iphone case",
        transport=transport,
        session_cookie="cookie",
        affiliate_cookie=None,  # no cookie -> Surface B raises NotImplementedError internally
        user_agent=UA,
    )

    assert len(items) == 2
    assert all(item.commission is None for item in items)


async def test_search_cookie_binding_error_raises_immediately_without_retry() -> None:
    transport = NoopTransport(get_responses=[{"error": 90309999, "error_msg": "cookie mismatch"}])

    with pytest.raises(SearchError) as exc_info:
        await search("iphone case", transport=transport, session_cookie="cookie", user_agent=UA)

    assert exc_info.value.code == 90309999
    assert exc_info.value.url is not None
    assert len(transport.get_calls) == 1  # no retry for cookie-binding failures


async def test_search_transient_error_retries_once_then_succeeds() -> None:
    transport = NoopTransport(
        get_responses=[
            {"error": 1, "error_msg": "too frequent"},
            _surface_a_response(1),
        ]
    )

    items = await search(
        "iphone case",
        transport=transport,
        session_cookie="cookie",
        user_agent=UA,
        affiliate_leg=False,
    )

    assert len(items) == 1
    assert len(transport.get_calls) == 2


async def test_search_transport_failure_raises_search_error_after_one_retry() -> None:
    transport = NoopTransport(get_responses=[ConnectionError("boom"), ConnectionError("boom")])

    with pytest.raises(SearchError):
        await search("iphone case", transport=transport, session_cookie="cookie", user_agent=UA)

    assert len(transport.get_calls) == 2


async def test_search_timeout_sets_is_timeout_marker() -> None:
    transport = NoopTransport(get_responses=[TimeoutError("timed out"), TimeoutError("timed out")])

    with pytest.raises(SearchError) as exc_info:
        await search("iphone case", transport=transport, session_cookie="cookie", user_agent=UA)

    assert exc_info.value.is_timeout is True
