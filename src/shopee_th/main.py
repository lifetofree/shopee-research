"""FastAPI app factory + uvicorn entry.

The factory is the single composition root: it wires settings, the
Transport, the OutputGenerator, the DB engine, CORS, static files, and the
API routes. The module-level `app = create_app()` instance keeps
`uvicorn src.shopee_th.main:app --reload` working without `--factory`.

Tests pass overrides via `create_app(settings=..., transport=..., generator=...)`
to swap the live collaborators for `NoopTransport` / `TemplateGenerator` /
in-memory SQLite.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from shopee_th import __version__
from shopee_th.api.routes import router as api_router
from shopee_th.config import Settings, get_settings
from shopee_th.models.db import init_db
from shopee_th.services.generation import OutputGenerator, get_generator
from shopee_th.services.transport import HttpTransport, Transport

logger = logging.getLogger(__name__)

# Path to the static files directory served at `/`. The frontend lives here
# once `build-single-page-html-js-frontend` lands; for v1 we ship a single
# placeholder page so the mount has something to serve.
STATIC_DIR = Path(__file__).resolve().parents[2] / "static"


class StatusResponse(BaseModel):
    """Uniform shape for the liveness endpoints."""

    status: str
    version: str


# --- Factory ---------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run init on startup; close resources on shutdown.

    `init_db` is idempotent (`create_all` is a no-op when tables exist), so
    it works for both the production startup and the test fixture that has
    already set up the schema.
    """
    settings: Settings = app.state.settings
    logging.basicConfig(level=settings.log_level)
    await init_db()
    try:
        yield
    finally:
        # Close the transport (releases the shared httpx client).
        transport = getattr(app.state, "transport", None)
        if transport is not None and hasattr(transport, "aclose"):
            try:
                await transport.aclose()
            except Exception:  # noqa: BLE001
                pass


def create_app(
    *,
    settings: Settings | None = None,
    transport: Transport | None = None,
    generator: OutputGenerator | None = None,
) -> FastAPI:
    """Application factory.

    The module-level `app = create_app()` instance resolves the
    collaborators from the environment (Settings + real HttpTransport +
    env-driven generator); tests pass overrides for the in-process transport
    and an in-memory DB.
    """
    settings = settings or get_settings()
    transport = transport or HttpTransport()
    # Pass settings.generator/gemini_* explicitly: get_generator() alone
    # reads os.environ, but pydantic-settings loads these from `.env`
    # directly without touching os.environ, so the two can disagree.
    generator = generator or get_generator(
        settings.generator,
        gemini_api_key=settings.gemini_api_key,
        gemini_model=settings.gemini_model,
    )

    app = FastAPI(
        title="shopee-th",
        version=__version__,
        description=(
            "Local FastAPI web app for Shopee Affiliate Thailand. "
            "See docs/SPEC.md for the full surface area."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.transport = transport
    app.state.generator = generator

    # --- CORS: localhost only --------------------------------------------
    # Browsers don't accept `*` in the origin part of CORS; we use a regex
    # so `http://localhost:5173`, `http://localhost:8788`, and any future
    # port all work without a code change.
    #
    # The Shopee origins are allowed because the browser extension's content
    # scripts POST captured items here directly from those pages (the MV3
    # background worker sleep/wake cycle is unreliable, so saves bypass it).
    # The app is localhost-only and single-user, so widening CORS to the two
    # Shopee origins carries no real exposure.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://localhost(:\d+)?|https://(affiliate\.)?shopee\.co\.th",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Liveness / health -------------------------------------------------
    @app.get("/health", response_model=StatusResponse, tags=["health"])
    def health() -> StatusResponse:
        return StatusResponse(status="ok", version=__version__)

    # --- API routes --------------------------------------------------------
    app.include_router(api_router)

    # --- Static files (frontend) ------------------------------------------
    # Mount last so the API and /health take priority. The directory is
    # created on demand so a fresh clone doesn't crash `uvicorn` on boot.
    static_dir = STATIC_DIR
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/",
        StaticFiles(directory=str(static_dir), html=True),
        name="static",
    )

    return app


# Module-level instance so `uvicorn src.shopee_th.main:app` works without
# `--factory` (and `make run` can use `--reload` cleanly).
app = create_app()


def run() -> None:  # pragma: no cover - exercised by the project script entry
    """Console entry: `uv run shopee-th` → uvicorn on localhost:8000."""
    import uvicorn

    uvicorn.run("shopee_th.main:app", host="127.0.0.1", port=8000, reload=False)
