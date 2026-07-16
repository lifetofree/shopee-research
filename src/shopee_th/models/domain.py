"""Pydantic DTOs for the search + persistence seams.

`Item` promotes `image`, `price`, `sold`, `commission` per the two-leg merge
contract in docs/SPEC.md; every other Surface A field (name, itemid, shopid,
ratings, ...) is preserved verbatim in `raw` so nothing upstream is lost
before it reaches SQLite persistence.

`SavedItemDTO` and `OutputDTO` are the API-contract shapes for persisted rows,
kept separate from the ORM models in `models/db.py` so the HTTP layer never
leaks SQLAlchemy types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Item(BaseModel):
    """A single search result, merged from Surface A (+ best-effort Surface B)."""

    source_id: str
    title: str

    # --- Two-leg merge contract fields ---
    image: str | None = None
    price: float | None = None
    sold: int | None = None
    commission: float | None = None

    raw: dict[str, Any] = Field(default_factory=dict)


class SavedItemDTO(BaseModel):
    """API shape for a persisted saved item. The full captured Item rides in `item`."""

    id: int
    query: str
    source_id: str
    item: Item
    saved_at: datetime

    @classmethod
    def from_orm_row(cls, row: Any) -> SavedItemDTO:
        """Build a DTO from a `SavedItem` ORM row, hydrating the JSON `payload`."""
        return cls(
            id=row.id,
            query=row.query,
            source_id=row.source_id,
            item=Item.model_validate_json(row.payload),
            saved_at=row.saved_at,
        )


class OutputDTO(BaseModel):
    """API shape for a persisted generation output."""

    id: int
    saved_item_id: int
    kind: str  # 'caption' | 'clip_prompt'
    body: str
    generated_at: datetime
