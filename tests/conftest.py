"""Shared pytest fixtures.

Bootstrap ticket left this empty; the persistence ticket adds a temp in-memory
SQLite engine + session factory so repository tests run offline and isolated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from shopee_th.models.db import Base, _enable_sqlite_fk
from shopee_th.models.domain import Item


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
