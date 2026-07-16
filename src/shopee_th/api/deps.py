"""FastAPI dependency-injection helpers.

The HTTP layer resolves its collaborators (Settings, Transport, OutputGenerator,
DB session) via these small factories. The production `create_app()` populates
`app.state` with the right instances; tests can do the same and pass them in
overrides.

For the DB session, the FastAPI Depends pattern is the natural fit: a per-request
session that the route owns, then closes. For the Transport / Generator /
Settings, the values are stable across the app's lifetime, so we read them from
`app.state` rather than spinning up per-request.
"""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from shopee_th.config import Settings
from shopee_th.models.db import get_session_factory
from shopee_th.services.generation import OutputGenerator
from shopee_th.services.transport import Transport


# --- App-state accessors ----------------------------------------------------


def get_settings(request: Request) -> Settings:
    """Resolve the `Settings` instance attached at app creation time."""
    return request.app.state.settings


def get_transport(request: Request) -> Transport:
    """Resolve the `Transport` attached at app creation time."""
    return request.app.state.transport


def get_generator(request: Request) -> OutputGenerator:
    """Resolve the `OutputGenerator` attached at app creation time."""
    return request.app.state.generator


# --- Per-request DB session -------------------------------------------------


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a fresh `AsyncSession` from the factory.

    The session is closed when the request finishes (success or error).
    Route handlers commit explicitly when they want to persist; the search
    routes don't open a session at all.
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session
