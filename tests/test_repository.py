"""Integration tests for the persistence layer.

Runs the repository functions against a fresh in-memory SQLite DB per test
(via the ``session`` fixture) and asserts round-trip, idempotency, listing
order, and cascade delete. No HTTP, no network.
"""

from __future__ import annotations

import pytest

from shopee_th.models.db import Output, SavedItem
from shopee_th.models.domain import Item, OutputDTO, SavedItemDTO
from shopee_th.models.repository import (
    add_output,
    delete_saved,
    get_saved,
    list_outputs,
    list_saved,
    save_item,
    to_output_dto,
    to_saved_dto,
)

pytestmark = pytest.mark.asyncio


# --- save_item: idempotency --------------------------------------------------


async def test_save_item_inserts_new_row(session, item_factory):
    item = item_factory()
    row = await save_item(session, item, query="headphones")
    await session.commit()

    assert row.id is not None
    assert row.source_id == item.source_id
    assert row.query == "headphones"
    # payload round-trips back into the original Item
    hydrated = Item.model_validate_json(row.payload)
    assert hydrated.title == item.title
    assert hydrated.price == item.price


async def test_save_item_is_idempotent_on_source_id(session, item_factory):
    item = item_factory(source_id="shop1.item42", title="First capture")

    first = await save_item(session, item, query="earbuds")
    await session.commit()

    # Re-save with a DIFFERENT query + mutated payload — must return the
    # original row unchanged (idempotent; first save wins).
    mutated = item.model_copy(update={"title": "Changed later", "price": 999.0})
    second = await save_item(session, mutated, query="different query")
    await session.commit()

    assert second.id == first.id
    assert second.query == "headphones" or second.query == "earbuds"  # original query kept
    # Payload was NOT overwritten.
    assert Item.model_validate_json(second.payload).title == "First capture"

    # Only one row exists.
    all_rows = await list_saved(session)
    assert len(all_rows) == 1


# --- list / get --------------------------------------------------------------


async def test_list_saved_returns_newest_first(session, item_factory):
    a = await save_item(session, item_factory(source_id="s.1"), query="q")
    b = await save_item(session, item_factory(source_id="s.2"), query="q")
    c = await save_item(session, item_factory(source_id="s.3"), query="q")
    await session.commit()

    rows = await list_saved(session)
    assert [r.id for r in rows] == [c.id, b.id, a.id]  # newest first


async def test_list_saved_empty_when_nothing_saved(session):
    assert await list_saved(session) == []


async def test_get_saved_returns_row_or_none(session, item_factory):
    item = item_factory()
    row = await save_item(session, item, query="q")
    await session.commit()

    found = await get_saved(session, row.id)
    assert found is not None
    assert found.source_id == item.source_id

    missing = await get_saved(session, 99999)
    assert missing is None


# --- delete + cascade --------------------------------------------------------


async def test_delete_saved_returns_true_and_removes_row(session, item_factory):
    item = item_factory()
    row = await save_item(session, item, query="q")
    await session.commit()

    assert await delete_saved(session, row.id) is True
    await session.commit()

    assert await get_saved(session, row.id) is None


async def test_delete_missing_returns_false(session):
    assert await delete_saved(session, 99999) is False


async def test_delete_saved_cascades_to_outputs(session, item_factory):
    item = item_factory()
    row = await save_item(session, item, query="q")
    await session.commit()

    await add_output(session, row.id, "caption", "first caption")
    await add_output(session, row.id, "clip_prompt", "first clip")
    await session.commit()

    assert len(await list_outputs(session, row.id)) == 2

    await delete_saved(session, row.id)
    await session.commit()

    # Outputs are gone via cascade.
    assert await list_outputs(session, row.id) == []


# --- outputs -----------------------------------------------------------------


async def test_add_output_preserves_history(session, item_factory):
    item = item_factory()
    row = await save_item(session, item, query="q")
    await session.commit()

    o1 = await add_output(session, row.id, "caption", "v1")
    o2 = await add_output(session, row.id, "caption", "v2")
    await session.commit()

    rows = await list_outputs(session, row.id, kind="caption")
    assert [r.body for r in rows] == ["v2", "v1"]  # newest first, both kept
    assert {r.id for r in rows} == {o1.id, o2.id}


async def test_list_outputs_filters_by_kind(session, item_factory):
    item = item_factory()
    row = await save_item(session, item, query="q")
    await session.commit()

    await add_output(session, row.id, "caption", "a caption")
    await add_output(session, row.id, "clip_prompt", "a clip")
    await session.commit()

    captions = await list_outputs(session, row.id, kind="caption")
    clips = await list_outputs(session, row.id, kind="clip_prompt")
    assert [r.body for r in captions] == ["a caption"]
    assert [r.body for r in clips] == ["a clip"]


# --- DTO hydration -----------------------------------------------------------


async def test_to_saved_dto_hydrates_payload(session, item_factory):
    item = item_factory(title="Hello THB", price=12.5)
    row = await save_item(session, item, query="hello")
    await session.commit()

    dto = to_saved_dto(row)
    assert isinstance(dto, SavedItemDTO)
    assert dto.item.title == "Hello THB"
    assert dto.item.price == 12.5
    assert dto.query == "hello"


async def test_to_output_dto_shape(session, item_factory):
    item = item_factory()
    row = await save_item(session, item, query="q")
    out = await add_output(session, row.id, "caption", "body text")
    await session.commit()

    dto = to_output_dto(out)
    assert isinstance(dto, OutputDTO)
    assert dto.kind == "caption"
    assert dto.body == "body text"
    assert dto.saved_item_id == row.id


# --- table-level constraints (defensive) -------------------------------------


async def test_saved_item_source_id_is_unique(session, item_factory):
    """The UNIQUE constraint fires at the DB level (not via the idempotent repo
    path, which short-circuits before INSERT)."""
    from sqlalchemy import insert

    await session.execute(
        insert(SavedItem).values(
            query="q", source_id="dup.1", payload='{"source_id":"dup.1","title":"x"}'
        )
    )
    await session.flush()
    # The second insert with the same source_id must violate the UNIQUE constraint.
    with pytest.raises(Exception):  # noqa: B017 - IntegrityError or sqlite Error
        await session.execute(
            insert(SavedItem).values(
                query="q", source_id="dup.1", payload='{"source_id":"dup.1","title":"y"}'
            )
        )
        await session.flush()


async def test_output_fk_blocks_orphan_insert(session):
    """An output row cannot reference a non-existent saved_item_id (FK).

    Requires ``PRAGMA foreign_keys=ON`` (enabled per-connection in db.create_engine
    and in the test fixture) — SQLite does not enforce FKs by default.
    """
    from sqlalchemy import insert

    with pytest.raises(Exception):  # noqa: B017 - IntegrityError (FK)
        await session.execute(insert(Output).values(saved_item_id=99999, kind="caption", body="x"))
        await session.flush()
