"""SQLAlchemy 2.x async ORM models + engine/session wiring.

Two tables per the `implement-sqlite-persistence` ticket (K1 decision):

- ``saved_items`` — one row per user-saved product. Idempotent on ``source_id``
  (UNIQUE); re-saving the same product returns the existing row and does NOT
  overwrite the captured payload.
- ``outputs`` — one row per generation event (caption / clip_prompt). No unique
  constraint: history is preserved across regenerations. Cascades on delete of
  the parent saved item.

The DB URL comes from ``Settings.db_url`` (env ``SHOPEE_TH_DB_URL``, default
``sqlite+aiosqlite:///./data/shopee_th.db``). ``init_db`` runs
``Base.metadata.create_all`` — acceptable for v1 per the ticket; no hand-written
migrations in this ticket.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import ForeignKey, Index, Integer, Text, func
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from shopee_th.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class SavedItem(Base):
    """A user-saved Shopee product captured at save time."""

    __tablename__ = "saved_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON blob of the full Item
    saved_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.current_timestamp()
    )

    outputs: Mapped[list[Output]] = relationship(
        back_populates="saved_item", cascade="all, delete-orphan"
    )


class Output(Base):
    """A single generation event (caption or clip_prompt) for a saved item."""

    __tablename__ = "outputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    saved_item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("saved_items.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # 'caption' | 'clip_prompt'
    body: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.current_timestamp()
    )

    saved_item: Mapped[SavedItem] = relationship(back_populates="outputs")

    __table_args__ = (Index("ix_outputs_saved_item_kind", "saved_item_id", "kind"),)


# --- Engine / session wiring -------------------------------------------------

# A module-level engine bound lazily to the configured DB URL. Tests override
# this via ``set_engine`` to point at an in-memory or temp-file DB.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _enable_sqlite_fk(dbapi_conn, _connection_record) -> None:
    """Enable ``PRAGMA foreign_keys=ON`` on each SQLite connection.

    SQLite does NOT enforce foreign keys by default; without this the
    ``ON DELETE CASCADE`` on ``outputs.saved_item_id`` and the FK constraint
    itself are silently ignored. This listener runs on every new raw DBAPI
    connection so production and tests both get enforcement.
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _ensure_sqlite_dir(url: str) -> None:
    """Create the parent directory for a file-based SQLite URL, if missing.

    A fresh clone has no `data/` directory, and aiosqlite doesn't create
    parent directories itself — without this, the default
    `sqlite+aiosqlite:///./data/shopee_th.db` fails on the very first
    connection attempt (`make run`'s startup, or the e2e/smoke test boot).
    """
    if not url.startswith("sqlite"):
        return
    database = make_url(url).database
    if not database or database == ":memory:":
        return
    Path(database).resolve().parent.mkdir(parents=True, exist_ok=True)


def create_engine(db_url: str | None = None) -> AsyncEngine:
    """Build an async engine for ``db_url`` (defaults to ``Settings.db_url``)."""
    url = db_url or get_settings().db_url
    _ensure_sqlite_dir(url)
    engine = create_async_engine(url, future=True)

    # SQLite needs per-connection FK enabling. Non-SQLite URLs ignore the listener.
    if url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(engine.sync_engine, "connect")
        def _on_connect(dbapi_conn, connection_record):  # noqa: ARG001
            _enable_sqlite_fk(dbapi_conn, connection_record)

    return engine


def get_engine() -> AsyncEngine:
    """Return the cached module-level engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def set_engine(engine: AsyncEngine) -> None:
    """Override the cached engine (used by tests to point at a temp DB)."""
    global _engine, _session_factory
    _engine = engine
    _session_factory = None  # force re-bind on next get_session_factory()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the current engine."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncSession:
    """FastAPI dependency: yields an ``AsyncSession`` from the factory."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_db(db_url: str | None = None) -> None:
    """Create all tables. Idempotent. Accepts an optional ``db_url`` for tests.

    Per the ticket, ``Base.metadata.create_all`` is acceptable for v1; this is
    not a migration system.
    """
    engine = create_engine(db_url) if db_url else get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Dispose the cached engine (test teardown)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
