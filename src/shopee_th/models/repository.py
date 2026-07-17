"""Async repository functions for the persistence layer.

Implements the six operations contracted by the `implement-sqlite-persistence`
ticket. Idempotency rule: re-saving the same ``source_id`` returns the existing
row and does NOT overwrite the captured payload (so the first save wins, by
design — the item as it was when the user first saved it).

All functions accept an ``AsyncSession`` so callers (FastAPI deps, tests) own
the session lifecycle and transaction boundaries.
"""

from __future__ import annotations

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from shopee_th.models.db import Output, SavedItem
from shopee_th.models.domain import Item, OutputDTO, SavedItemDTO


async def save_item(session: AsyncSession, item: Item, query: str) -> SavedItem:
    """Persist ``item`` under ``query``. Idempotent on ``source_id``.

    If a row with the same ``source_id`` already exists, return that existing
    row unchanged (the payload is NOT overwritten — first save wins). Otherwise
    insert a new row and return it.
    """
    existing = await session.scalar(select(SavedItem).where(SavedItem.source_id == item.source_id))
    if existing is not None:
        return existing

    row = SavedItem(
        query=query,
        source_id=item.source_id,
        payload=item.model_dump_json(),
    )
    session.add(row)
    await session.flush()  # populate row.id without committing
    return row


async def list_saved(session: AsyncSession) -> list[SavedItem]:
    """Return all saved items, newest first (by id as a monotonic proxy for saved_at)."""
    result = await session.execute(select(SavedItem).order_by(desc(SavedItem.id)))
    return list(result.scalars().all())


async def get_saved(session: AsyncSession, id: int) -> SavedItem | None:
    """Return the saved item with ``id``, or ``None`` if missing."""
    return await session.get(SavedItem, id)


async def delete_saved(session: AsyncSession, id: int) -> bool:
    """Delete the saved item with ``id``. Returns True if a row was deleted.

    Cascades to child ``outputs`` rows via the ORM relationship
    (``cascade="all, delete-orphan"``) and the DB-level ``ON DELETE CASCADE``.
    """
    row = await session.get(SavedItem, id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def add_output(session: AsyncSession, saved_item_id: int, kind: str, body: str) -> Output:
    """Append a generation output row. No unique constraint — history is preserved."""
    row = Output(saved_item_id=saved_item_id, kind=kind, body=body)
    session.add(row)
    await session.flush()
    return row


async def delete_outputs(session: AsyncSession, saved_item_id: int, kind: str) -> int:
    """Delete all outputs of ``kind`` for ``saved_item_id``. Returns the count deleted.

    Used when regenerating: the UI shows one caption/clip at a time, so prior
    outputs of the same kind are cleared before the new one is added.
    """
    stmt = delete(Output).where(
        Output.saved_item_id == saved_item_id, Output.kind == kind
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def list_outputs(
    session: AsyncSession, saved_item_id: int, kind: str | None = None
) -> list[Output]:
    """Return outputs for ``saved_item_id``, newest first.

    Filter by ``kind`` ('caption' | 'clip_prompt') when provided; otherwise
    return outputs of all kinds.
    """
    stmt = select(Output).where(Output.saved_item_id == saved_item_id)
    if kind is not None:
        stmt = stmt.where(Output.kind == kind)
    stmt = stmt.order_by(desc(Output.id))
    result = await session.execute(stmt)
    return list(result.scalars().all())


# --- DTO hydration helpers ---------------------------------------------------


def to_saved_dto(row: SavedItem) -> SavedItemDTO:
    """Hydrate a ``SavedItem`` ORM row into the API ``SavedItemDTO``."""
    return SavedItemDTO.from_orm_row(row)


def to_output_dto(row: Output) -> OutputDTO:
    """Hydrate an ``Output`` ORM row into the API ``OutputDTO``."""
    return OutputDTO(
        id=row.id,
        saved_item_id=row.saved_item_id,
        kind=row.kind,
        body=row.body,
        generated_at=row.generated_at,
    )
