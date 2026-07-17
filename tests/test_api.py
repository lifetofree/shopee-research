"""End-to-end tests for the HTTP API.

Boots the FastAPI app with `NoopTransport` (search) + temp in-memory SQLite
(persistence) + `TemplateGenerator` (generation) and walks every documented
route via `httpx.AsyncClient(transport=ASGITransport(app=app))`.

This is the primary e2e seam per the spec — the API contract is the
authoritative surface. If these tests pass, the wire contract holds.
"""

from __future__ import annotations

import httpx
import pytest

from shopee_th.config import Settings
from shopee_th.main import create_app
from shopee_th.services.transport import NoopTransport, TransportResponse

# `app` and `client` fixtures live in tests/conftest.py (shared with test_smoke.py).


# --- Canned data -------------------------------------------------------------


def _surface_a_ok(*items: dict) -> TransportResponse:
    """Canned Surface A response with the given item rows."""
    return TransportResponse(status=200, json={"items": list(items), "total_count": len(items)})


def _item(
    itemid: str = "111",
    *,
    title: str = "iPhone 15 silicone case",
    image: str = "abc123",
    price_micros: int = 12_900_000,  # ฿129
    sold: int = 1234,
) -> dict:
    return {
        "item_basic": {
            "itemid": itemid,
            "image": image,
            "price": price_micros,
            "price_min": price_micros,
            "historical_sold": sold,
            "name": title,
        }
    }


# --- Health ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_ok(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]


# --- /api/search -----------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_items_with_canned_transport(
    client: httpx.AsyncClient, app
) -> None:
    """Canned Surface A response → /api/search returns parsed items."""
    noop: NoopTransport = app.state.noop_transport
    noop.push(
        _surface_a_ok(
            _item("111", title="iPhone 15 case"),
            _item("222", title="Another product"),
        )
    )
    resp = await client.post("/api/search", json={"query": "iphone", "limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["source_id"] == "111"
    assert body["items"][0]["title"] == "iPhone 15 case"
    assert body["items"][0]["image"] == "https://cf.shopee.co.th/file/abc123"
    assert body["items"][0]["price"] == pytest.approx(129.0)


@pytest.mark.asyncio
async def test_search_uses_configured_user_agent_not_hardcoded_default() -> None:
    """Regression: Settings.user_agent must reach the outgoing Surface A request.

    A real session_cookie is bound to the browser fingerprint that produced
    it (docs/research/data-surfaces.md §2.5) -- replaying it with a stale
    hardcoded User-Agent gets rejected with `error: 90309999` even though
    the cookie itself is valid. This exercises settings.user_agent -> the
    actual request headers with a distinctive value, the same class of
    "config exists but isn't wired to the call site" bug that broke
    SHOPEE_TH_GENERATOR earlier in this project.
    """
    distinctive_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/149.0.0.0 Safari/537.36"
    settings = Settings(
        session_cookie="SPC=test-cookie",
        user_agent=distinctive_ua,
        db_url="sqlite+aiosqlite:///:memory:",
    )
    noop = NoopTransport()
    noop.push(_surface_a_ok(_item("111")))
    application = create_app(settings=settings, transport=noop)

    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/search", json={"query": "iphone", "limit": 5})

    get_call = next(call for call in noop.calls if call["method"] == "GET")
    assert get_call["headers"]["User-Agent"] == distinctive_ua


@pytest.mark.asyncio
async def test_search_empty_query_returns_400_via_pydantic(
    client: httpx.AsyncClient,
) -> None:
    """Pydantic catches min_length=1 on the request body."""
    resp = await client.post("/api/search", json={"query": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_empty_result_returns_200_with_empty_items(
    client: httpx.AsyncClient, app
) -> None:
    noop: NoopTransport = app.state.noop_transport
    noop.push(TransportResponse(status=200, json={"items": []}))
    resp = await client.post("/api/search", json={"query": "no-such-product"})
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


@pytest.mark.asyncio
async def test_search_upstream_error_maps_to_502(
    client: httpx.AsyncClient, app
) -> None:
    noop: NoopTransport = app.state.noop_transport
    noop.push(TransportResponse(status=200, json={"error": 90309999, "error_msg": "Need login"}))
    resp = await client.post("/api/search", json={"query": "iphone"})
    assert resp.status_code == 502
    body = resp.json()
    # FastAPI wraps HTTPException(detail=...) under "detail"; the ApiError
    # fields are at the top level of that object.
    assert body["detail"]["error"] == "search_failed"
    assert body["detail"]["code"] == "90309999"
    assert "refresh-cookie" in (body["detail"]["guidance"] or "")


@pytest.mark.asyncio
async def test_search_limit_capped_at_20(
    client: httpx.AsyncClient, app
) -> None:
    noop: NoopTransport = app.state.noop_transport
    noop.push(_surface_a_ok(_item("111")))
    resp = await client.post("/api/search", json={"query": "x", "limit": 999})
    assert resp.status_code == 200
    # The Transport recorded the cap.
    get_call = next(c for c in noop.calls if c["method"] == "GET")
    assert get_call["params"]["limit"] == 20


# --- /api/saved ------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_list_get_outputs_delete_round_trip(
    client: httpx.AsyncClient, app
) -> None:
    """The primary e2e from the ticket body: full lifecycle in one test."""
    noop: NoopTransport = app.state.noop_transport
    noop.push(
        _surface_a_ok(
            _item("111", title="iPhone 15 case"),
            _item("222", title="Another product"),
        )
    )

    # 1. search
    resp = await client.post("/api/search", json={"query": "iphone", "limit": 5})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    first = items[0]
    second = items[1]

    # 2. save
    resp = await client.post("/api/saved", json={"item": first, "query": "iphone"})
    assert resp.status_code == 200
    saved = resp.json()
    assert saved["query"] == "iphone"
    assert saved["item"]["source_id"] == "111"
    first_id = saved["id"]

    # 3. save the same item again — idempotent, same row, no duplicate.
    resp = await client.post("/api/saved", json={"item": first, "query": "different"})
    assert resp.status_code == 200
    again = resp.json()
    assert again["id"] == first_id
    # First-save-wins: the original query is kept.
    assert again["query"] == "iphone"

    # 4. list_saved — exactly one row
    resp = await client.get("/api/saved")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1

    # 5. caption
    resp = await client.post(f"/api/saved/{first_id}/caption")
    assert resp.status_code == 200
    cap = resp.json()
    assert cap["body"]
    assert "generated_at" in cap
    # Caption is at most 250 chars total per the generator's contract.
    assert len(cap["body"]) <= 250

    # 6. clip-prompt
    resp = await client.post(f"/api/saved/{first_id}/clip-prompt")
    assert resp.status_code == 200
    clip = resp.json()
    assert len(clip["body"]) <= 300

    # 7. caption again — replace mode: the prior caption is replaced, not
    #    stacked. (One caption at a time per item — re-clicking refreshes.)
    resp = await client.post(f"/api/saved/{first_id}/caption")
    assert resp.status_code == 200

    # 8. list outputs by kind — only the latest caption remains.
    resp = await client.get(f"/api/saved/{first_id}/outputs?kind=caption")
    assert resp.status_code == 200
    outputs = resp.json()["outputs"]
    assert len(outputs) == 1  # replace mode: prior caption was cleared

    resp = await client.get(f"/api/saved/{first_id}/outputs?kind=clip_prompt")
    assert resp.status_code == 200
    assert len(resp.json()["outputs"]) == 1

    # 9. save the second item; verify ordering (newest first)
    resp = await client.post("/api/saved", json={"item": second, "query": "iphone"})
    assert resp.status_code == 200
    second_id = resp.json()["id"]
    assert second_id > first_id  # autoincrement

    resp = await client.get("/api/saved")
    assert resp.status_code == 200
    listed = resp.json()["items"]
    assert [it["id"] for it in listed] == [second_id, first_id]

    # 10. delete first; outputs cascade
    resp = await client.delete(f"/api/saved/{first_id}")
    assert resp.status_code == 204
    resp = await client.get(f"/api/saved/{first_id}/outputs?kind=caption")
    assert resp.status_code == 404  # saved item gone

    # 11. delete the second
    resp = await client.delete(f"/api/saved/{second_id}")
    assert resp.status_code == 204
    resp = await client.get("/api/saved")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_save_rejects_missing_source_id_with_400(
    client: httpx.AsyncClient,
) -> None:
    """An item without `source_id` is rejected with 400 (idempotency invariant)."""
    bad = {
        "source_id": "",
        "title": "x",
        "image": "img",
        "price": 0.0,
        "sold": 0,
        "commission": None,
        "raw": {},
    }
    resp = await client.post("/api/saved", json={"item": bad, "query": "q"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "invalid_input"


@pytest.mark.asyncio
async def test_delete_missing_returns_404(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.delete("/api/saved/99999")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "not_found"


@pytest.mark.asyncio
async def test_outputs_for_missing_saved_item_returns_404(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/api/saved/99999/outputs?kind=caption")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_caption_for_missing_saved_item_returns_404(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post("/api/saved/99999/caption")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_outputs_kind_query_param_rejects_unknown_kind(
    client: httpx.AsyncClient,
) -> None:
    """The `kind` query is regex-validated to `caption|clip_prompt`."""
    resp = await client.get("/api/saved/1/outputs?kind=garbage")
    assert resp.status_code == 422


# --- CORS preflight --------------------------------------------------------


@pytest.mark.asyncio
async def test_cors_allows_localhost_origin(
    client: httpx.AsyncClient,
) -> None:
    """Localhost origins (any port) are allowed; nothing else is."""
    resp = await client.options(
        "/api/search",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.headers.get("access-control-allow-origin") in (
        "http://localhost:5173",
        # some Starlette versions echo the origin
        "*",
    )


# --- Generator wiring --------------------------------------------------------


def test_create_app_generator_respects_settings_when_not_overridden() -> None:
    # Regression: create_app() used to call get_generator() with no args,
    # which reads os.environ directly — but pydantic-settings loads
    # SHOPEE_TH_GENERATOR from `.env` without ever touching os.environ, so
    # a `.env`-only setting was silently ignored. This exercises the
    # settings -> generator wiring with no explicit `generator=` override.
    from shopee_th.services.generation import LLMGenerator, TemplateGenerator

    stub_settings = Settings(generator="stub", db_url="sqlite+aiosqlite:///:memory:")
    stub_app = create_app(settings=stub_settings, transport=NoopTransport())
    assert isinstance(stub_app.state.generator, TemplateGenerator)

    llm_settings = Settings(generator="llm", db_url="sqlite+aiosqlite:///:memory:")
    llm_app = create_app(settings=llm_settings, transport=NoopTransport())
    assert isinstance(llm_app.state.generator, LLMGenerator)
