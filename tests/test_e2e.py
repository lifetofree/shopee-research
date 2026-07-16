"""Live end-to-end test: boots a real uvicorn process and drives the full
search -> save -> list -> caption -> outputs -> clip-prompt -> outputs ->
delete -> list-empty loop against the actual Shopee Affiliate TH portal.

Unlike tests/test_api.py (in-process ASGI transport + NoopTransport mocks),
this hits a subprocess-booted server over real HTTP with the real
HttpTransport, using `SHOPEE_TH_E2E_COOKIE` as the session cookie. Skipped
(not failed) when that env var isn't set — run via `make e2e`.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parent.parent
BOOT_TIMEOUT_SECONDS = 15.0


def _free_port() -> int:
    """Ask the OS for an unused localhost port so parallel runs don't collide."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest_asyncio.fixture
async def live_client() -> AsyncIterator[httpx.AsyncClient]:
    """Boot a real uvicorn subprocess against the live portal; skip if no cookie."""
    cookie = os.environ.get("SHOPEE_TH_E2E_COOKIE")
    if not cookie:
        pytest.skip("set SHOPEE_TH_E2E_COOKIE to run against the live portal")

    port = _free_port()
    env = {**os.environ, "SHOPEE_TH_SESSION_COOKIE": cookie}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "shopee_th.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=15.0) as client:
            await _wait_for_boot(client, proc)
            yield client
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


async def _wait_for_boot(client: httpx.AsyncClient, proc: subprocess.Popen) -> None:
    deadline = time.monotonic() + BOOT_TIMEOUT_SECONDS
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"uvicorn exited early with code {proc.returncode}")
        try:
            resp = await client.get("/health")
            if resp.status_code == 200:
                return
        except httpx.TransportError as exc:
            last_exc = exc
        await asyncio.sleep(0.2)
    raise RuntimeError(f"uvicorn didn't come up within {BOOT_TIMEOUT_SECONDS:.0f}s") from last_exc


@pytest.mark.asyncio
async def test_full_lifecycle_against_live_portal(live_client: httpx.AsyncClient) -> None:
    # 1. search
    search_resp = await live_client.post("/api/search", json={"query": "iphone case", "limit": 5})
    assert search_resp.status_code == 200, search_resp.text
    items = search_resp.json()["items"]
    assert items, "live search returned no items — is SHOPEE_TH_E2E_COOKIE still valid?"
    item = items[0]

    # 2. save, then re-save the same item to check idempotency on source_id
    save_resp = await live_client.post("/api/saved", json={"item": item, "query": "iphone case"})
    assert save_resp.status_code == 200, save_resp.text
    saved_id = save_resp.json()["id"]

    resave_resp = await live_client.post("/api/saved", json={"item": item, "query": "iphone case"})
    assert resave_resp.status_code == 200
    assert resave_resp.json()["id"] == saved_id

    # 3. list
    list_resp = await live_client.get("/api/saved")
    assert list_resp.status_code == 200
    assert any(row["id"] == saved_id for row in list_resp.json()["items"])

    # 4. caption generation + outputs
    caption_resp = await live_client.post(f"/api/saved/{saved_id}/caption")
    assert caption_resp.status_code == 200
    assert caption_resp.json()["body"]

    caption_outputs_resp = await live_client.get(
        f"/api/saved/{saved_id}/outputs", params={"kind": "caption"}
    )
    assert caption_outputs_resp.status_code == 200
    assert len(caption_outputs_resp.json()["outputs"]) >= 1

    # 5. clip-prompt generation + outputs
    clip_resp = await live_client.post(f"/api/saved/{saved_id}/clip-prompt")
    assert clip_resp.status_code == 200
    assert clip_resp.json()["body"]

    clip_outputs_resp = await live_client.get(
        f"/api/saved/{saved_id}/outputs", params={"kind": "clip_prompt"}
    )
    assert clip_outputs_resp.status_code == 200
    assert len(clip_outputs_resp.json()["outputs"]) >= 1

    # 6. delete, then confirm it's gone from the list
    delete_resp = await live_client.delete(f"/api/saved/{saved_id}")
    assert delete_resp.status_code == 204

    final_list_resp = await live_client.get("/api/saved")
    assert final_list_resp.status_code == 200
    assert not any(row["id"] == saved_id for row in final_list_resp.json()["items"])
