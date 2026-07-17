"""HTTP API route handlers.

Per the `implement-fastapi-http-layer` ticket body, the eight documented
routes plus a `/health` liveness endpoint. All responses follow the spec's
documented DTO shapes; errors return a uniform `ApiError` body with a stable
`error` code so the frontend can branch on it without parsing prose.

Empty `SearchResponse` is `{"items": []}` (never a 404). `SearchError` maps
to 502 with the structured error body. Save is idempotent on
`item.source_id`. Delete cascades to outputs. Caption / clip-prompt
generation persists as `outputs` rows (history preserved).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from shopee_th.api.deps import (
    get_generator,
    get_session,
    get_settings,
    get_transport,
)
from shopee_th.api.schemas import (
    ApiError,
    CaptionResponse,
    OutputsListResponse,
    SaveRequest,
    SavedListResponse,
    SearchRequest,
    SearchResponse,
)
from shopee_th.config import Settings
from shopee_th.models.db import Output
from shopee_th.models.domain import Item, OutputDTO, SavedItemDTO
from shopee_th.models.repository import (
    add_output,
    delete_outputs,
    delete_saved,
    get_saved,
    list_outputs,
    list_saved,
    save_item,
    to_output_dto,
    to_saved_dto,
)
from shopee_th.services.generation import OutputGenerator
from shopee_th.services.search import DEFAULT_USER_AGENT, MAX_LIMIT, SearchError, search
from shopee_th.services.transport import Transport

router = APIRouter(prefix="/api", tags=["api"])


# --- /api/search -----------------------------------------------------------


@router.post(
    "/search",
    response_model=SearchResponse,
    responses={
        200: {"model": SearchResponse},
        502: {"model": ApiError, "description": "Upstream Shopee call failed."},
    },
)
async def search_endpoint(
    body: SearchRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    transport: Annotated[Transport, Depends(get_transport)],
) -> SearchResponse:
    """Search Shopee Affiliate TH for products matching `body.query`.

    Empty result → 200 with `{"items": []}` (never an error). Upstream
    failure → 502 with a structured `ApiError` body so the frontend can
    show the `guidance` line (e.g. "run make refresh-cookie").
    """
    limit = min(body.limit, MAX_LIMIT)
    try:
        items = await search(
            transport,
            query=body.query,
            limit=limit,
            session_cookie=settings.session_cookie,
            # Falls back to the hardcoded default only for a cookie-less/
            # anonymous session; a real session_cookie is fingerprint-bound
            # to the browser that produced it (see Settings.user_agent).
            user_agent=settings.user_agent or DEFAULT_USER_AGENT,
        )
    except SearchError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=ApiError(
                error="search_failed",
                message=str(e),
                url=e.url,
                code=str(e.code) if e.code is not None else None,
                guidance=e.guidance,
            ).model_dump(),
        ) from e
    return SearchResponse(items=items)


# --- /api/saved ------------------------------------------------------------


@router.get(
    "/saved",
    response_model=SavedListResponse,
)
async def list_saved_endpoint(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SavedListResponse:
    """Return all saved items, newest first."""
    rows = await list_saved(session)
    return SavedListResponse(items=[to_saved_dto(r) for r in rows])


@router.post(
    "/saved",
    response_model=SavedItemDTO,
    responses={
        200: {"model": SavedItemDTO, "description": "Created or already existed (idempotent)."},
        400: {"model": ApiError, "description": "Malformed payload."},
    },
)
async def save_item_endpoint(
    body: SaveRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SavedItemDTO:
    """Save an item idempotently. Re-saving the same `source_id` returns the
    existing row unchanged (first save wins; payload is never overwritten).
    """
    if not body.item.source_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ApiError(
                error="invalid_input",
                message="item.source_id is required for save idempotency.",
            ).model_dump(),
        )
    row = await save_item(session, body.item, query=body.query)
    await session.commit()
    return to_saved_dto(row)


@router.delete(
    "/saved/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Deleted (cascaded to outputs)."},
        404: {"model": ApiError, "description": "No saved item with that id."},
    },
)
async def delete_saved_endpoint(
    item_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Delete a saved item. Cascades to its `outputs` rows."""
    deleted = await delete_saved(session, item_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ApiError(
                error="not_found",
                message=f"No saved item with id={item_id}.",
            ).model_dump(),
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- /api/saved/{id}/caption, /clip-prompt --------------------------------


async def _generate_and_persist(
    session: AsyncSession,
    generator: OutputGenerator,
    item_id: int,
    kind: str,
) -> Output:
    """Shared helper: verify the saved item exists, generate, persist, return row."""
    saved = await get_saved(session, item_id)
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ApiError(
                error="not_found",
                message=f"No saved item with id={item_id}.",
            ).model_dump(),
        )
    item = Item.model_validate_json(saved.payload)
    if kind == "caption":
        body = generator.caption(item)
    else:
        body = generator.clip_prompt(item)
    # Replace mode: clear prior outputs of the same kind so each click shows
    # one caption/clip (not a stacking history). The user re-clicks to refresh.
    await delete_outputs(session, item_id, kind=kind)
    return await add_output(session, item_id, kind=kind, body=body)


@router.post(
    "/saved/{item_id}/caption",
    response_model=CaptionResponse,
    responses={
        200: {"model": CaptionResponse},
        404: {"model": ApiError},
    },
)
async def generate_caption_endpoint(
    item_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
    generator: Annotated[OutputGenerator, Depends(get_generator)],
) -> CaptionResponse:
    """Generate a Thai caption for the saved item, persist it, return it."""
    row = await _generate_and_persist(session, generator, item_id, kind="caption")
    await session.commit()
    return CaptionResponse(body=row.body, generated_at=row.generated_at)


@router.post(
    "/saved/{item_id}/clip-prompt",
    response_model=CaptionResponse,
    responses={
        200: {"model": CaptionResponse},
        404: {"model": ApiError},
    },
)
async def generate_clip_prompt_endpoint(
    item_id: Annotated[int, Path(ge=1)],
    session: Annotated[AsyncSession, Depends(get_session)],
    generator: Annotated[OutputGenerator, Depends(get_generator)],
) -> CaptionResponse:
    """Generate an English 8-second clip-prompt for the saved item, persist it, return it."""
    row = await _generate_and_persist(session, generator, item_id, kind="clip_prompt")
    await session.commit()
    return CaptionResponse(body=row.body, generated_at=row.generated_at)


@router.get(
    "/saved/{item_id}/outputs",
    response_model=OutputsListResponse,
    responses={
        200: {"model": OutputsListResponse},
        404: {"model": ApiError},
    },
)
async def list_outputs_endpoint(
    item_id: Annotated[int, Path(ge=1)],
    kind: Annotated[str | None, Query(pattern="^(caption|clip_prompt)$")] = None,
    session: Annotated[AsyncSession, Depends(get_session)] = ...,
) -> OutputsListResponse:
    """Return generation history for the saved item, newest first.

    Filter by `kind` (`caption` or `clip_prompt`) when supplied; otherwise
    return outputs of all kinds.
    """
    saved = await get_saved(session, item_id)
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ApiError(
                error="not_found",
                message=f"No saved item with id={item_id}.",
            ).model_dump(),
        )
    rows = await list_outputs(session, item_id, kind=kind)
    return OutputsListResponse(outputs=[to_output_dto(r) for r in rows])
