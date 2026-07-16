"""Shared pytest fixtures.

Bootstrap ticket left this empty; the persistence ticket adds a temp in-memory
SQLite engine + session factory so repository tests run offline and isolated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from shopee_th.config import Settings
from shopee_th.main import create_app
from shopee_th.models.db import Base, _enable_sqlite_fk, set_engine
from shopee_th.models.domain import Item
from shopee_th.services.generation import TemplateGenerator
from shopee_th.services.transport import NoopTransport


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Yield an ``AsyncSession`` bound to a fresh in-memory SQLite database.

    Each test gets its own schema (created via ``create_all``) and a clean
    session. ``StaticPool`` + ``:memory:`` keeps a single connection alive so
    the in-memory DB isn't dropped between the ``create_all`` and the test body.
    Foreign keys are enforced via the same per-connection pragma as production.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine.sync_engine, "connect", _enable_sqlite_fk)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess

    await engine.dispose()


@pytest.fixture
def item_factory() -> Callable[..., Item]:
    """Return a factory building ``Item`` instances for tests."""

    counter = {"n": 0}

    def _make(**overrides) -> Item:
        counter["n"] += 1
        n = counter["n"]
        defaults: dict = {
            "source_id": f"shop{n}.item{n}",
            "title": f"Product {n}",
            "image": f"https://cf.shopee.co.th/file/img{n}",
            "price": float(100 + n),
            "sold": n * 5,
            "commission": None,
            "raw": {"itemid": n, "shopid": 100, "name": f"Product {n}"},
        }
        defaults.update(overrides)
        return Item(**defaults)

    return _make


@pytest_asyncio.fixture
async def app() -> AsyncIterator:
    """Build a fresh FastAPI app per test with in-memory DB + NoopTransport.

    Shared by tests/test_api.py (exhaustive per-route coverage) and
    tests/test_smoke.py (the fast "did it come up at all" check) so both
    boot the app the same way, against mocks, with no live network.
    """
    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine.sync_engine, "connect", _enable_sqlite_fk)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    set_engine(engine)

    settings = Settings(
        session_cookie="SPC=test-cookie",
        affiliate_cookie="SPC_AFF=test-cookie",
        generator="stub",
        db_url="sqlite+aiosqlite:///:memory:",
        log_level="WARNING",
    )
    transport = NoopTransport()
    generator = TemplateGenerator()

    application = create_app(settings=settings, transport=transport, generator=generator)
    application.state.noop_transport = transport  # convenient for tests
    application.state.in_memory_engine = engine

    try:
        yield application
    finally:
        # Reset module-level engine so subsequent tests start clean.
        set_engine(None)  # type: ignore[arg-type]
        await engine.dispose()


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    """An httpx AsyncClient bound to the app's ASGI transport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
