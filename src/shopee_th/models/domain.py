"""Pydantic DTOs for the search seam.

`Item` promotes `image`, `price`, `sold`, `commission` per the two-leg merge
contract in docs/SPEC.md; every other Surface A field (name, itemid, shopid,
ratings, ...) is preserved verbatim in `raw` so nothing upstream is lost
before it reaches SQLite persistence.
"""

from __future__ import annotations

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
