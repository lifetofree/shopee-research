---
name: Implement FastAPI HTTP layer
labels: [wayfinder:task]
status: closed
assignee: Mavis
blocked_by: [research-map-data-surfaces, bootstrap-python-project, implement-search-service, implement-sqlite-persistence, implement-output-templates]
parent: map
created: 2026-07-16
claimed: 2026-07-16
closed: 2026-07-16
unblocks: [build-single-page-html-js-frontend, dev-runbook-and-smoke-test]
---

## Resolution (2026-07-16)

**Asset:** `src/shopee_th/api/{schemas,deps,routes}.py` + updated `main.py` + `static/index.html` placeholder + `tests/test_api.py`. `uv run pytest` → 76/76 green (12 e2e API tests + 30 generation tests + 17 search tests + 14 repository tests + 2 health tests + 1 static-mount test). `uvicorn src.shopee_th.main:app` boots; `/health` returns OK, `/` serves the placeholder HTML, `/api/saved` returns `{"items": []}`.

**Files added:**

- `src/shopee_th/api/schemas.py` — `SearchRequest` (query, limit with `ge=1`), `SearchResponse`, `SaveRequest` (item, query), `SavedListResponse`, `CaptionResponse` (body, `generated_at: datetime`), `OutputsListResponse`, `ApiError` (uniform error body).
- `src/shopee_th/api/deps.py` — `get_settings`, `get_transport`, `get_generator` (read from `app.state`), `get_session` (per-request `AsyncSession` via the factory).
- `src/shopee_th/api/routes.py` — 7 documented routes under `/api` + `/health`:
  - `POST /api/search` — body `{"query", "limit"}`; cap `limit` at 20; `SearchError` → 502 with `ApiError(detail=...)`; empty result → 200 `{"items": []}`.
  - `GET /api/saved` — newest first.
  - `POST /api/saved` — body `{"item", "query"}`; idempotent on `source_id`; rejects empty `source_id` with 400.
  - `DELETE /api/saved/{item_id}` — 204 on success, 404 if missing; cascades to outputs.
  - `POST /api/saved/{item_id}/caption` — generate, persist, return `{body, generated_at}`.
  - `POST /api/saved/{item_id}/clip-prompt` — symmetric.
  - `GET /api/saved/{item_id}/outputs?kind=caption|clip_prompt` — newest first; `kind` validated by regex.
- `src/shopee_th/main.py` — updated: `lifespan` runs `init_db()` on startup + closes the transport on shutdown; `create_app(settings=, transport=, generator=)` factory with all-overridable; `CORSMiddleware` with `allow_origin_regex=r"http://localhost(:\d+)?"` (any localhost port); static-files mount at `/` serving `static/`; `init_db` and `STATIC_DIR` creation on demand so a fresh clone boots cleanly.
- `static/index.html` — placeholder pointing at `/docs` and `/redoc`; the `build-single-page-html-js-frontend` ticket replaces this with the real SPA.
- `tests/test_api.py` — 12 e2e tests: health, search (canned NoopTransport, empty query → 422, empty result → 200, upstream error → 502 with guidance, limit cap), full lifecycle (search → save → idempotent re-save → list → caption → outputs → clip-prompt → re-caption → cascade delete → empty list), 400 on missing `source_id`, 404 on missing saved item, kind-query validation, CORS preflight.
- `tests/test_health.py` — updated: `/` now serves the static placeholder (was JSON), `/health` still works.

**Decisions worth surfacing:**

- **`create_app()` is a thin composition root with all collaborators overridable.** The module-level `app = create_app()` (no args) keeps `uvicorn src.shopee_th.main:app --reload` working without `--factory`; the test fixture passes `settings=`, `transport=`, `generator=` overrides. This is the seam that makes the e2e tests fast and deterministic (NoopTransport, in-memory SQLite, TemplateGenerator).
- **CORS uses `allow_origin_regex=r"http://localhost(:\d+)?"`** rather than `allow_origins=[…]`, because CORS spec doesn't accept wildcards in the origin part — only in the port. The regex matches any localhost port (`5173`, `8788`, anything), so the frontend can use either Vite's default port or the `wrangler pages dev` port without code changes.
- **The `kind` query param on `GET /api/saved/{id}/outputs` is regex-validated** to `^(caption|clip_prompt)$` at the FastAPI level — Pydantic returns 422 on unknown values, which is the right shape for a client-side bug (not a 400 / 404).
- **`/health` is registered as a route BEFORE the static-files mount at `/`.** Static files take priority on the matched path, so `/health` resolves first; `/` falls through to the static mount.
- **Errors return a uniform `ApiError` body via `HTTPException(detail=ApiError(...).model_dump())`.** The frontend can branch on `body.detail.error` (a stable code like `search_failed`, `not_found`, `invalid_input`) without parsing prose. The `SearchError.url`, `code`, and `guidance` fields propagate to the wire verbatim.
- **`SearchError` maps to 502 (bad gateway)** — the request is well-formed from our side, but the upstream failed. The frontend can distinguish "you wrote a bad request" (400/422) from "Shopee rejected it" (502) by status alone.
- **`init_db()` runs in the FastAPI lifespan**, not at module import time. This keeps `from shopee_th.main import app` side-effect-free for tests that want to use a different engine.
- **Static-files directory is created on demand** (`STATIC_DIR.mkdir(parents=True, exist_ok=True)`) so a fresh clone that hasn't built the frontend yet can still boot uvicorn and see the placeholder.

**Acceptance check (per ticket):**

- ✅ All 7 documented routes registered under `/api` prefix.
- ✅ `SearchError` → 502 with structured body; empty result → 200 `{"items": []}`.
- ✅ Save is idempotent on `source_id` (verified end-to-end).
- ✅ Delete returns 204 on success, 404 if missing.
- ✅ Caption / clip-prompt persist as `outputs` rows; history preserved across regenerations.
- ✅ `/api/saved/{id}/outputs?kind=...` newest first; `kind` validated.
- ✅ Static-files mount at `/` serving the placeholder.
- ✅ CORS allows `http://localhost:*` only.
- ✅ No auth on the web UI.
- ✅ Pydantic request/response DTOs separate from ORM models.
- ✅ `init_db` runs on startup; works in production and in tests.
- ✅ Single pytest e2e (`test_save_list_get_outputs_delete_round_trip`) walks the full lifecycle: search → save → idempotent re-save → list → caption → clip-prompt → re-caption → list outputs by kind → save second item → list ordered → delete first (cascades) → delete second → empty list. Plus 11 focused tests for edge cases.

**Out of scope (per ticket):** UI is unchanged — the `build-single-page-html-js-frontend` ticket lands the real SPA and replaces `static/index.html`.

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
