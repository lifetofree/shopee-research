---
name: Implement FastAPI HTTP layer
labels: [wayfinder:task]
status: open
assignee: unassigned
blocked_by: [research-map-data-surfaces, bootstrap-python-project, implement-search-service, implement-sqlite-persistence, implement-output-templates]
parent: map
created: 2026-07-16
---

## Question

Wire the existing modules into a FastAPI app on the scaffold from the bootstrap ticket. No UI yet (that's a separate ticket).

Required routes:

- `POST /api/search` — body `{"query": str, "limit"?: int=20}` → calls the search service → returns `{"items": [Item, ...]}`. Cap `limit` at 20. Map `SearchError` → 502 with a structured error body; empty result → 200 with `{"items": []}`.
- `GET /api/saved` → `{"items": [SavedItemDTO, ...]}` newest first.
- `POST /api/saved` — body `{"item": Item, "query": str}` → saves idempotently (same `source_id` returns the existing row), returns the `SavedItemDTO`. 200 if created or already existed; 400 on malformed payload.
- `DELETE /api/saved/{id}` → 204 on success, 404 if missing. Cascades to outputs in the DB.
- `POST /api/saved/{id}/caption` → calls generator, persists as `outputs` row, returns `{"body": "..."}` + `{"generated_at": "..."}`.
- `POST /api/saved/{id}/clip-prompt` → symmetric.
- `GET /api/saved/{id}/outputs?kind=caption|clip_prompt` → `{"outputs": [...]}` newest first.
- Static-files mount at `/` serving the future frontend's directory (placeholder mount OK; frontend lives in its own ticket).
- CORS: allow `http://localhost:*` only. No auth.
- Pydantic request/response DTOs separate from ORM models; explicit shape validated by `pytest` against `httpx.AsyncClient(app=app)`.

Smoke test (in `tests/`): a single pytest that boots the app with an in-process transport + temp DB, hits every route end-to-end (search → save → list → caption → outputs → delete).

This ticket ships an API, not a UI.
