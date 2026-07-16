"""Transport seam for outbound Shopee HTTP calls.

`search.py` depends on the `Transport` Protocol, never on httpx directly, so
the search service stays library-importable and unit-testable without a
network.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx


class Transport(Protocol):
    """Thin async HTTP seam. Returns parsed JSON bodies."""

    async def get(
        self, url: str, *, headers: dict[str, str], params: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def post(
        self, url: str, *, headers: dict[str, str], json: dict[str, Any]
    ) -> dict[str, Any]: ...


class HttpTransport:
    """Production transport backed by `httpx.AsyncClient`."""

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self._timeout_seconds = timeout_seconds

    async def get(
        self, url: str, *, headers: dict[str, str], params: dict[str, Any]
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()

    async def post(
        self, url: str, *, headers: dict[str, str], json: dict[str, Any]
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=json)
            response.raise_for_status()
            return response.json()


class NoopTransport:
    """Test double: replays queued responses (or raises queued exceptions) in call order."""

    def __init__(
        self,
        get_responses: list[dict[str, Any] | Exception] | None = None,
        post_responses: list[dict[str, Any] | Exception] | None = None,
    ) -> None:
        self._get_responses: list[dict[str, Any] | Exception] = list(get_responses or [])
        self._post_responses: list[dict[str, Any] | Exception] = list(post_responses or [])
        self.get_calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def get(
        self, url: str, *, headers: dict[str, str], params: dict[str, Any]
    ) -> dict[str, Any]:
        self.get_calls.append((url, headers, params))
        if not self._get_responses:
            raise AssertionError("NoopTransport.get called more times than responses were queued")
        result = self._get_responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def post(
        self, url: str, *, headers: dict[str, str], json: dict[str, Any]
    ) -> dict[str, Any]:
        self.post_calls.append((url, headers, json))
        if not self._post_responses:
            raise AssertionError("NoopTransport.post called more times than responses were queued")
        result = self._post_responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
