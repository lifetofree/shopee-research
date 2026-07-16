"""Always-on smoke test: boots the app against mocks, no live network required.

Distinct from tests/test_api.py's exhaustive per-endpoint coverage — this is
the fast "did the app come up at all" check `make smoke` runs on every dev
machine: the frontend page renders, and the API actually responds.
"""

from __future__ import annotations

import httpx
import pytest

from shopee_th.services.transport import TransportResponse


@pytest.mark.asyncio
async def test_smoke_frontend_page_renders(client: httpx.AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "<html" in resp.text.lower()


@pytest.mark.asyncio
async def test_smoke_health_responds_ok(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_smoke_search_api_responds_ok(app, client: httpx.AsyncClient) -> None:
    app.state.noop_transport.push(TransportResponse(status=200, json={"items": [], "total_count": 0}))
    resp = await client.post("/api/search", json={"query": "smoke test query"})
    assert resp.status_code == 200
    assert resp.json()["items"] == []
