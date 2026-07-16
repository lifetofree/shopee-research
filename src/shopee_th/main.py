"""FastAPI app factory + uvicorn entry.

This bootstrap ticket ships a hello-world app: `/` and `/health` both return
`{"status": "ok"}`. Downstream tickets add the search / saved / outputs routes.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from fastapi import FastAPI
from pydantic import BaseModel

from shopee_th import __version__
from shopee_th.config import get_settings

logger = logging.getLogger(__name__)


class StatusResponse(BaseModel):
    """Uniform shape for the bootstrap health endpoints."""

    status: str
    version: str


def create_app() -> FastAPI:
    """Application factory. `uvicorn src.shopee_th.main:app` resolves this."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title="shopee-th",
        version=__version__,
        description=(
            "Local FastAPI web app for Shopee Affiliate Thailand. "
            "See docs/SPEC.md for the full surface area."
        ),
    )

    @app.get("/", response_model=StatusResponse)
    def root() -> StatusResponse:
        """Liveness ping for the dev server boot check."""
        return StatusResponse(status="ok", version=__version__)

    @app.get("/health", response_model=StatusResponse)
    def health() -> StatusResponse:
        """Health endpoint for `make smoke` and the bootstrap pytest."""
        return StatusResponse(status="ok", version=__version__)

    return app


# Module-level instance so `uvicorn src.shopee_th.main:app` works without
# `--factory` (and `make run` can use `--reload` cleanly).
app = create_app()


def run() -> None:  # pragma: no cover - exercised by the project script entry
    """Console entry: `uv run shopee-th` → uvicorn on localhost:8000."""
    import uvicorn

    uvicorn.run("shopee_th.main:app", host="127.0.0.1", port=8000, reload=False)


async def _async_unused() -> AsyncIterator[None]:  # pragma: no cover
    """Silence 'AsyncIterator imported but unused' if linters get picky.

    Real async dependencies (DB session, transport) land in later tickets.
    """
    yield None
