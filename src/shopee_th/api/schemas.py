"""Request/response Pydantic DTOs for the HTTP API.

Deliberately separate from `models.domain` (the persistence/search DTOs) so
the wire contract can evolve independently of the storage and search layer.
Each schema here is a thin envelope: the body shape that hits the wire, not
the rich internal types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shopee_th.models.domain import Item


# --- /api/search -----------------------------------------------------------


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = Field(min_length=1, description="Search keyword. Empty/whitespace is rejected by validation.")
    limit: int = Field(default=20, ge=1, description="Max items to return. Capped at 20 by the route.")


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[Item]


# --- /api/saved ------------------------------------------------------------


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item: Item = Field(description="The item to save (idempotent on `item.source_id`).")
    query: str = Field(min_length=1, description="The search string the user typed when saving.")


class SavedListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[Any] = Field(description="SavedItemDTO rows (newest first). Typed as `Any` to avoid coupling the wire to the persistence DTO.")


# --- /api/saved/{id}/caption, /clip-prompt --------------------------------


class CaptionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    body: str
    generated_at: datetime


class OutputsListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    outputs: list[Any]


# --- error envelope --------------------------------------------------------


class ApiError(BaseModel):
    """Uniform error body for 4xx/5xx responses (matches the spec's "structured body" ask)."""

    model_config = ConfigDict(extra="ignore")

    error: str = Field(description="Stable error code (e.g. `search_failed`, `not_found`).")
    message: str = Field(description="Human-readable message.")
    url: str | None = Field(default=None, description="The offending upstream URL, when applicable.")
    code: str | int | None = Field(default=None, description="The upstream error code, when applicable.")
    guidance: str | None = Field(default=None, description="One-line human hint (e.g. `run make refresh-cookie`).")
