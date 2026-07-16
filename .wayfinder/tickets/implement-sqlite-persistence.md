---
name: Implement SQLite persistence (saved_items + outputs)
labels: [wayfinder:task]
status: closed
assignee: unassigned
blocked_by: [bootstrap-python-project]
parent: map
created: 2026-07-16
---

## Question

Implement the storage layer with two tables per the K1 decision:

- **`saved_items`** — one row per user-saved product.
  - `id` (PK, autoincrement int),
  - `query` (text — the search string the user typed when saving),
  - `source_id` (text — Shopee's product id from the API response; **UNIQUE** constraint, to make save idempotent),
  - `payload` (JSON-blob text — the full `Item` model captured at save time so we never lose upstream fields),
  - `saved_at` (timestamp, default `now()`).
- **`outputs`** — one row per generation event.
  - `id` (PK, autoincrement int),
  - `saved_item_id` (FK → `saved_items.id`, `ON DELETE CASCADE`),
  - `kind` (`'caption' | 'clip_prompt'` text, indexed with `saved_item_id`),
  - `body` (text),
  - `generated_at` (timestamp, default `now()`).
  - No unique constraint — history is preserved across regenerations.

Supporting code:

- SQLAlchemy 2.x (or SQLModel) models matching the schema above.
- A tiny migration that creates tables on first run (`Base.metadata.create_all(engine)` is acceptable for v1; do not hand-write migrations in this ticket).
- `src/shopee_th/models/repository.py` exposing **async** functions: `save_item(item: Item, query: str) -> SavedItem` (idempotent: re-saving the same `source_id` returns the existing row, does NOT overwrite the payload), `list_saved() -> list[SavedItem]` (newest first), `get_saved(id: int) -> SavedItem | None`, `delete_saved(id: int) -> bool`, `add_output(saved_item_id: int, kind: str, body: str) -> Output`, `list_outputs(saved_item_id: int, kind: str) -> list[Output]` (newest first).
- DB lives at `data/shopee_th.db`; SQLite URL driven from env; gitignored.
- Pydantic DTOs (separate from ORM models) for the API contract.
- One integration test that runs the repository functions against a temp sqlite file (use `:memory:` or a tmp file) and asserts round-trip + idempotency.

This ticket produces NO HTTP routes, NO UI.
