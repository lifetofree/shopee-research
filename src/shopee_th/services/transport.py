"""Transport Protocol and its two implementations.

The search service depends on `Transport`, not on httpx directly. Two impls:

- `HttpTransport` — production httpx-backed.
- `NoopTransport` — test double, scripted via a queue of `TransportResponse`s.

`TransportResponse` is the data envelope returned by both: the parsed JSON
body plus status + headers. This is the smallest shape that lets the search
service distinguish Shopee's quirky "200 with an error body" responses from
real failures (5xx, network errors).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx


@dataclass(frozen=True)
class TransportResponse:
    """One HTTP transaction, normalized to the fields the search service uses."""

    status: int
    json: dict[str, Any] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class Transport(Protocol):
    """Async transport for outbound HTTP. Every Shopee call goes through this."""

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> TransportResponse: ...

    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> TransportResponse: ...

    async def aclose(self) -> None: ...


# --- Production -----------------------------------------------------------


class HttpTransport:
    """httpx-backed Transport. Single shared `AsyncClient` per instance.

    The 10s timeout matches the ticket's contract; the search service applies
    its own retry/backoff on top of this. `aclose()` is a no-op kept for
    symmetry with the Protocol (so the API layer can `await transport.aclose()`
    on shutdown if it wants to).
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> TransportResponse:
        resp = await self._client.get(url, headers=dict(headers or {}), params=dict(params or {}))
        return TransportResponse(
            status=resp.status_code,
            json=_safe_json(resp),
            headers=dict(resp.headers),
        )

    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> TransportResponse:
        resp = await self._client.post(url, headers=dict(headers or {}), json=dict(json or {}))
        return TransportResponse(
            status=resp.status_code,
            json=_safe_json(resp),
            headers=dict(resp.headers),
        )

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()


def _safe_json(resp: httpx.Response) -> dict[str, Any]:
    """Parse JSON if the body looks like JSON; return `{}` for empty/HTML bodies.

    Cloudflare and upstream failures sometimes return HTML 200/5xx pages; the
    search service treats them as "no data" rather than raising.
    """
    if not resp.content:
        return {}
    try:
        data = resp.json()
    except (ValueError, json.JSONDecodeError if False else Exception):  # noqa: PIE786
        return {}
    return data if isinstance(data, dict) else {}


# --- Test double ----------------------------------------------------------


class NoopTransport:
    """Scripted transport for unit tests.

    Tests push `TransportResponse`s (or `Exception`s) onto a queue. Each call
    pops the next entry. A `get` call can be answered with a `post` response
    and vice versa — the test chooses which script the surface A or B leg
    reads. Per-call `default_response` is used when the queue is empty (lets
    tests pin a "this call always returns X" without queueing).
    """

    def __init__(self, default_response: TransportResponse | None = None) -> None:
        self._queue: list[TransportResponse | Exception] = []
        self._default = default_response
        self.calls: list[dict[str, Any]] = []

    def push(self, response: TransportResponse | Exception) -> None:
        """Append a scripted response (or raise-on-call) to the queue."""
        self._queue.append(response)

    def push_many(self, responses: Iterable[TransportResponse | Exception]) -> None:
        for r in responses:
            self.push(r)

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> TransportResponse:
        return await self._dispatch("GET", url, headers=headers, params=params)

    async def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> TransportResponse:
        return await self._dispatch("POST", url, headers=headers, json=json)

    async def aclose(self) -> None:
        return None

    async def _dispatch(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> TransportResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "params": dict(params or {}),
                "json": dict(json or {}),
            }
        )
        if self._queue:
            entry = self._queue.pop(0)
            if isinstance(entry, Exception):
                raise entry
            return entry
        if self._default is None:
            raise AssertionError(
                f"NoopTransport: no scripted response for {method} {url}; "
                f"call {len(self.calls)} and queue is empty."
            )
        return self._default
