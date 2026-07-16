"""Pydantic DTOs for the search/save/outputs API contract.

These types are the boundary between the upstream Shopee payloads, the
search service, the persistence layer, and the HTTP API. They are deliberately
separate from the SQLAlchemy ORM models (in `models.db`) so the API contract
can evolve independently of storage.

Two notes about the `Item` shape (reconciled with the persistence ticket's
conftest fixtures + test assertions):

- `price` is a `float` (THB can have satang). The search service emits whole
  numbers today (the upstream is micro-units divided by 100_000), but the
  persistence layer and tests round-trip floats, so the type is open.
- `title` is a promoted field. The caption / clip-prompt generator reads it
  directly; everything else (brand, category, etc.) lives in `raw` and is
  re-derivable from the upstream payload at any time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shopee_th.models.db import Output, SavedItem


class Item(BaseModel):
    """A single product returned by the search service.

    The promoted fields are denormalized for the UI; `raw` carries the full
    upstream payload so the persistence layer can re-derive anything else
    later without losing data. `source_id` is Shopee's item id and is the
    idempotency key for the `saved_items` table.
    """

    model_config = ConfigDict(extra="ignore")

    source_id: str = Field(description="Shopee's item id; idempotency key for saves.")
    title: str = Field(default="", description="Product title (used by the caption/clip-prompt generator).")
    image: str = Field(description="Full product image URL.")
    price: float = Field(ge=0.0, description="Price in THB (float; satang allowed).")
    sold: int = Field(ge=0, description="Historical sold count.")
    commission: float | None = Field(
        default=None,
        ge=0.0,
        description="Commission rate as a fraction (0.06 = 6%). None until Surface B lands.",
    )
    raw: dict[str, Any] = Field(
        default_factory=dict,
        description="Full upstream payload for this item. Source of truth for fields not promoted.",
    )


class SearchErrorPayload(BaseModel):
    """Optional Shopee-side error envelope (a 200 can still carry this)."""

    model_config = ConfigDict(extra="ignore")

    error: int | str | None = None
    error_msg: str | None = None
    message: str | None = None
    warning: str | None = None
    tracking_id: str | None = None
    ct_bucket: str | None = Field(default=None, alias="ct_bucket")


class SavedItemDTO(BaseModel):
    """API shape for a saved item (returned by GET /api/saved, POST /api/saved)."""

    model_config = ConfigDict(extra="ignore")

    id: int
    query: str
    saved_at: str = Field(
        description="ISO-8601 timestamp string for the API surface."
    )
    item: Item

    @classmethod
    def from_orm_row(cls, row: SavedItem) -> "SavedItemDTO":
        """Hydrate a `SavedItem` ORM row into the API DTO.

        The row's `payload` is the JSON-serialized `Item`; we re-validate it
        through Pydantic so any corruption surfaces as a 500 (not a silent
        empty object). `saved_at` is serialized to ISO-8601 for the API.
        """
        item = Item.model_validate_json(row.payload)
        saved_at = (
            row.saved_at.isoformat()
            if isinstance(row.saved_at, datetime)
            else str(row.saved_at)
        )
        return cls(
            id=row.id,
            query=row.query,
            saved_at=saved_at,
            item=item,
        )


class OutputDTO(BaseModel):
    """API shape for a single generated output (caption or clip-prompt)."""

    model_config = ConfigDict(extra="ignore")

    id: int
    saved_item_id: int
    kind: str  # 'caption' | 'clip_prompt'
    body: str
    generated_at: datetime
