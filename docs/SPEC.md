---
name: Shopee Affiliate TH — local web app
labels: [spec, ready-for-agent]
status: open
created: 2026-07-16
tracker: local-markdown
parent: .wayfinder/map.md
---

# Shopee Affiliate TH — local web app

> Synthesized from `.wayfinder/map.md` and the 10 tickets under `.wayfinder/tickets/`. This is the spec; tickets remain the unit-of-work breakdown for individual sessions.

---

## Problem Statement

A user (Shopee Affiliate Thailand partner) needs to find products in the affiliate portal by typing a name, see the four key fields (image, commission, price, sold), and turn each saved item into ready-to-post promotional copy — a Thai caption with English hashtags (≤250 chars total) and an English 8-second vertical video brief. They do this work on their own laptop, on demand, and do not want to use the Shopee Open API (out of scope by their definition). The portal itself does not offer a "search → save → caption" workflow; today this is copy-paste across three browser tabs per product.

The user also does not want to write a real LLM integration in this iteration — they want a templated stub that produces useful output now and can be swapped for an LLM in a follow-up without touching the call sites.

## Solution

A local FastAPI web app on `localhost:8000`, single-page HTML/JS UI (vanilla, no framework), authenticating to Shopee Affiliate Thailand via a user-supplied session cookie that the user captures once via a Playwright helper. Search hits the storefront search endpoint (Surface A) for image/price/sold and the affiliate portal endpoint (Surface B) for commission in a best-effort two-leg merge. The user can save items to a local SQLite store (idempotent on Shopee's product id) and generate a Thai caption + English clip prompt for each saved item via a `OutputGenerator` Protocol — a `TemplateGenerator` ships in this iteration, a real `LLMGenerator` is a follow-up.

The dev experience is end-to-end runnable from a clean clone: `uv sync`, `make refresh-cookie` (one-time interactive), `make run` → search → save → generate. `make e2e` exercises every API endpoint against the real portal (gated on a cookie env var), `make smoke` runs an offline mock version (always on).

## User Stories

A comprehensive enumeration. Each story is a contract the spec promises.

### Setup and developer experience

1. As a developer on a clean laptop, I can run `git clone` → `uv sync` → `make run` and have a working app on `http://localhost:8000` in under 5 minutes (no Python venv to wire by hand, no global installs).
2. As a developer, I can run `make test` and see all unit tests pass on the first run.
3. As a developer, I can run `make smoke` (no env required) and have a mocked end-to-end test pass to confirm the app boots and the API responds.
4. As a developer, I can run `make e2e` with `SHOPEE_TH_E2E_COOKIE` set, and have every API endpoint hit the real portal end-to-end; without the env var, the test is skipped with a clear message rather than failed.
5. As a developer, I can run `make dev-reset` to wipe `data/shopee_th.db` and `.env` (with confirmation prompt) and start from a clean state.
6. As a developer, I can read the `README.md` and find Prereqs, First-time setup, Run, Use, and Troubleshoot sections — no need to read source to know how to use the app.

### Cookie and authentication

7. As a user, I can run `make refresh-cookie` once and have a headed Chromium open to `shopee.co.th` and `affiliate.shopee.co.th`; I log in interactively when prompted, and the app persists my session cookies to `.env` for the app to replay.
8. As a user, I can re-run `make refresh-cookie` idempotently (overwrites `.env`).
9. As a developer, I can see `make refresh-cookie` exit non-zero if the login flow times out or the post-login signal never fires, with a clear error message.
10. As a user, I do not enter any password, cookie, or secret in the web UI — the UI has no login fields; secrets live in `.env` on my laptop only.

### Search

11. As a user, I can type a product name into a search bar and press Enter (or click a search button) and see matching products rendered as a grid: thumbnail, product name, price, sold count, commission — per row.
12. As a user, a re-search replaces the result grid (previous results do not accumulate).
13. As a user, if the search returns zero results, I see an explicit empty state (not a silently blank grid).
14. As a user, if the search fails (network error, cookie expired, upstream 5xx), I see a dismissible error banner with the server-supplied message — not a silent "request failed" toast.
15. As a user, I cannot ask the app to search more than 20 results at a time (the API caps `limit` at 20).
16. As a user, the price is in THB (e.g. "฿1,290"), the sold count is human-readable (e.g. "ขายแล้ว 1.2K" or "1,234"), and commission is shown as a percentage (e.g. "6%").
17. As a developer, I can hit `POST /api/search` directly with a JSON body and get a JSON response matching the documented DTO shape.

### Save

18. As a user, I can click "Save" on any search result and have the item appear in my Saved Items section immediately.
19. As a user, a double-click on "Save" produces exactly one row (not two, not "saving…" forever).
20. As a user, re-saving an item I've already saved (same Shopee product) does not duplicate the row — the server is idempotent on `source_id`.
21. As a user, I can see my saved items in newest-first order.
22. As a user, I can click "Remove" on a saved item and have it disappear from the list, with its generation history also gone (cascading delete).
23. As a user, if a save or delete fails, I see a dismissible error banner — not a silent reload.

### Generation

24. As a user, I can click "Generate caption" on a saved item and see a Thai caption with English hashtags appear below the item in a read-only text area.
25. As a user, I can click "Generate clip prompt" on a saved item and see an English 8-second video brief appear in the same shape.
26. As a user, I can re-generate a caption or clip prompt and the previous one is preserved as history (newest first).
27. As a user, I can click "Copy to clipboard" on any generated output and have the full text on my clipboard.
28. As a developer, switching from `TemplateGenerator` to a real LLM is a one-line env-var change (`SHOPEE_TH_GENERATOR=llm`); no call sites need to change.
29. As a developer, the `LLMGenerator` skeleton is present in the codebase (raising `NotImplementedError`) so the interface slot is explicit and a follow-up can fill it.
30. As a user, a generated caption is always ≤250 chars total (body + hashtags) and the body is in Thai with 4–7 English hashtags.
31. As a user, a generated clip prompt is in English, ≤300 chars, and references the product title or a sensible fallback.
32. As a developer, the templated generator handles empty product titles, missing brands, and missing categories without throwing — it produces a useful placeholder instead.

### Operations and reliability

33. As a user, if my session cookie has expired, I see a clear "cookie expired" indication in the UI and the README's Troubleshoot section tells me to run `make refresh-cookie`.
34. As a developer, the app surfaces upstream errors (Shopee's `error: 90309999` for cookie-binding failures, 5xx, network timeouts) with structured `SearchError` attributes — not opaque 500s.
35. As a developer, the search service does a single retry with linear backoff on transient upstream failures, and re-raises a `SearchError` on `error: 90309999` (which is cookie-binding, not retriable).
36. As a developer, every outbound Shopee call goes through a `Transport` Protocol with two implementations (`HttpTransport` for production, `NoopTransport` for tests).
37. As a developer, the search service is library-importable — it does not import FastAPI, app config, or DB code.

### Empirical discovery (Surface B)

38. As a developer, I can run `make capture-affiliate-traffic`, log in once to `affiliate.shopee.co.th` in the headed Chromium, type a search term, and have all network calls dumped to `docs/research/affiliate-observed-traffic.json` for inspection.
39. As a developer, that dump contains ≥3 distinct request types for the affiliate portal, and at least one matches the inferred GraphQL shape (`productOfferV2` or `product_search`-style query) so we can extract a concrete Surface B contract.

## Implementation Decisions

### Stack and tooling (pinned)

- **Python ≥ 3.11** with **`uv`** as the package manager (lockfile committed).
- **FastAPI** + **uvicorn[standard]** for the HTTP layer.
- **SQLAlchemy 2.x async** for SQLite; Pydantic DTOs separate from ORM models.
- **httpx** (async) for Surface A; **Playwright (Python)** for the cookie helper and Surface B fallback.
- **pydantic-settings** for env config; **python-dotenv** to load `.env`.
- **pytest** + **pytest-asyncio** for tests.
- No LLM client in this iteration; the `LLMGenerator` stub is a `NotImplementedError` placeholder.
- No front-end framework — vanilla HTML/CSS/JS, no build step.

### Folder layout

```
shopee-research/
├── pyproject.toml            # uv-managed; pinned deps
├── uv.lock
├── Makefile                  # run, test, lint, e2e, smoke, dev-reset, refresh-cookie, capture-affiliate-traffic
├── README.md
├── .env.example              # placeholder keys, no real secrets
├── .gitignore                # .env, .venv, .playwright, data/*.db, __pycache__, *.pyc, .pytest_cache
├── index.html                # SPA (linked app.js + styles.css)
├── app.js
├── styles.css
├── src/
│   └── shopee_th/
│       ├── __init__.py
│       ├── main.py           # FastAPI app factory + uvicorn entry
│       ├── config.py         # pydantic-settings
│       ├── api/              # route handlers (search, saved, outputs)
│       │   └── routes.py
│       ├── services/
│       │   ├── search.py     # two-leg merge, Transport Protocol
│       │   ├── transport.py  # HttpTransport, NoopTransport
│       │   └── generation.py # OutputGenerator Protocol, TemplateGenerator, LLMGenerator stub
│       ├── models/
│       │   ├── domain.py     # Pydantic DTOs (Item, SavedItemDTO, OutputDTO)
│       │   ├── orm.py        # SQLAlchemy models (SavedItem, Output)
│       │   └── repository.py # async repo functions
│       └── templates/        # caption + clip-prompt template strings (if extracted)
├── scripts/
│   ├── refresh_cookie.py     # `make refresh-cookie`
│   └── capture_affiliate_traffic.py  # `make capture-affiliate-traffic`
├── tests/
│   ├── conftest.py           # temp DB fixture, app fixture
│   ├── test_search.py
│   ├── test_repository.py
│   ├── test_generation.py
│   ├── test_api.py           # httpx.AsyncClient(app=app) end-to-end
│   └── test_smoke.py
├── docs/
│   ├── SPEC.md               # this file
│   └── research/
│       ├── data-surfaces.md
│       └── affiliate-observed-traffic.json
└── .wayfinder/
    ├── map.md
    └── tickets/              # 10 tickets, unit of work for individual sessions
```

### Configuration (env vars)

| Key | Source | Purpose |
|-----|--------|---------|
| `SHOPEE_TH_SESSION_COOKIE` | `.env` (cookie helper) | `; `-joined cookies for `shopee.co.th` (Surface A) |
| `SHOPEE_TH_AFFILIATE_COOKIE` | `.env` (cookie helper) | `; `-joined cookies for `affiliate.shopee.co.th` (Surface B) |
| `SHOPEE_TH_AFFILIATE_ID` | `.env` | Empty string for now; filled empirically if needed |
| `SHOPEE_TH_GENERATOR` | `.env` | `stub` (default) → `TemplateGenerator`; `llm` → `LLMGenerator` (not implemented this iteration) |
| `SHOPEE_TH_DB_URL` | `.env` | `sqlite+aiosqlite:///./data/shopee_th.db` (default) |
| `SHOPEE_TH_E2E_COOKIE` | env (test only) | If set, `make e2e` hits the real portal; otherwise skips |
| `SHOPEE_TH_LOG_LEVEL` | `.env` | `INFO` default |

### Search: two-leg merge contract

**Surface A (closed) — `GET https://shopee.co.th/api/v4/search/search_items`**

- Required headers: `User-Agent` (desktop Chrome UA from the same browser that produced the cookie), `cookie: $SHOPEE_TH_SESSION_COOKIE`, `referer: https://shopee.co.th/`, `x-api-source: pc`, `af-ac-enc-dat: null`.
- Query params: `by=relevancy`, `limit=<user-limit capped at 20>`, `keyword=<urlencoded query>`, `newest=<offset>`, `order=desc`, `page_type=search`, `scenario=PAGE_SEARCH`, `version=2`.
- Field extraction:
  - `image` ← `items[i].item_basic.image`, prefixed with literal `https://cf.shopee.co.th/file/`.
  - `price` ← `round(items[i].item_basic.price / 100000)` in THB; fall back to `price_min` if `price` looks IP-tampered.
  - `sold` ← `items[i].item_basic.historical_sold`.
  - `commission` ← `null` from Surface A.

**Surface B (open — best-effort until empirical capture lands)**

- Endpoint family: `POST https://affiliate.shopee.co.th/graphql` or similar (TBD; concrete shape comes from `capture-affiliate-portal-traffic`).
- Auth: `cookie: $SHOPEE_TH_AFFILIATE_COOKIE`.
- Per-item fields expected: `commissionRate` (e.g. "0.06" = 6%), `sellerCommissionRate`, `shopeeCommissionRate`, `commission` (= price × rate), `sales`/`sold`, `priceMin`/`priceMax`, `productName`, `shopName`, `imageUrl` (already full URL).

**Merge semantics:**

- `search(query, limit, affiliate_leg=True)` calls Surface A first → `Item` rows with image/price/sold.
- If `affiliate_leg=True`, it then attempts Surface B keyed by `(shopid, itemid)` from the storefront result.
- `Item.commission` is populated where the affiliate leg succeeded, left `null` otherwise.
- If the affiliate leg raises `NotImplementedError` or returns no data, the function still returns the Surface A rows. No exception is propagated for the commission phase alone.
- Single retry with linear backoff for `error_msg`-bearing 200s and `error: 90309999` cookie-bound failures (which usually mean *not the same browser*; raise `SearchError` with guidance rather than retry into the same failure).
- Treat response as empty (`[]`) when `items` is missing/empty. Never raise on no result.
- `SearchError(str)` for upstream failures, with the offending URL and the `error` code from Shopee attached as attributes.
- `httpx.AsyncClient` with 10 s timeout.

**Transport seam (Protocol):**

```python
class Transport(Protocol):
    async def get(self, url: str, *, headers: dict, params: dict) -> dict: ...
    async def post(self, url: str, *, headers: dict, json: dict) -> dict: ...
```

Two implementations:
- `HttpTransport` — production httpx-backed.
- `NoopTransport` — test double returning canned responses.

The search service depends on `Transport` (injected), not on httpx directly.

### Persistence (SQLite)

**`saved_items`** — one row per user-saved product.

- `id` (PK, autoincrement int)
- `query` (text — the search string the user typed when saving)
- `source_id` (text — Shopee's product id from the API response; **UNIQUE** for idempotent save)
- `payload` (JSON-blob text — the full `Item` model captured at save time, so we never lose upstream fields)
- `saved_at` (timestamp, default `now()`)

**`outputs`** — one row per generation event.

- `id` (PK, autoincrement int)
- `saved_item_id` (FK → `saved_items.id`, `ON DELETE CASCADE`)
- `kind` (`'caption' | 'clip_prompt'`, indexed with `saved_item_id`)
- `body` (text)
- `generated_at` (timestamp, default `now()`)
- No unique constraint — history is preserved across regenerations.

**Repository functions (async, `src/shopee_th/models/repository.py`):**

- `save_item(item: Item, query: str) -> SavedItem` — idempotent: re-saving the same `source_id` returns the existing row, does **not** overwrite the payload.
- `list_saved() -> list[SavedItem]` — newest first.
- `get_saved(id: int) -> SavedItem | None`
- `delete_saved(id: int) -> bool`
- `add_output(saved_item_id: int, kind: str, body: str) -> Output`
- `list_outputs(saved_item_id: int, kind: str) -> list[Output]` — newest first.

DB lives at `data/shopee_th.db` (gitignored). `Base.metadata.create_all(engine)` is acceptable for v1; no hand-written migrations.

### Generation: Protocol-based swap

```python
class OutputGenerator(Protocol):
    def caption(self, item: Item) -> str: ...
    def clip_prompt(self, item: Item) -> str: ...
```

**`TemplateGenerator` (default, env=`stub`):**

- `caption(item)`:
  - Thai body (≤180 chars) drawing from `item.title`, `item.brand` if present, the price, and the sold count (natural Thai: "ขายแล้ว X ชิ้น").
  - Appends 4–7 English hashtags chosen deterministically: `#ShopeeTH`, `#<category-slug>`, `#<price-band>`, plus 2 derived from the item.
  - Total `len(caption) ≤ 250`. Truncate body if needed; drop lowest-priority hashtags first.
  - Handles empty title, missing brand, missing category gracefully — no exceptions, sensible placeholder.
- `clip_prompt(item)`:
  - 1–2 sentence English brief for an 8-second vertical video.
  - Shape: `"Vertical 9:16, 8s, hand-held close-up of {title} on a clean surface, upbeat Thai-market styling, ..."`.
  - ≤300 chars, contains the title (or fallback).

**`LLMGenerator` (env=`llm`, not implemented this iteration):** raises `NotImplementedError`.

**Factory:** `get_generator() -> OutputGenerator` reads `SHOPEE_TH_GENERATOR` from env (default `"stub"`).

### HTTP API (FastAPI)

| Method + path | Body / query | Response | Notes |
|---------------|--------------|----------|-------|
| `POST /api/search` | `{"query": str, "limit"?: int=20}` | `{"items": [Item, ...]}` | Cap `limit` at 20. `SearchError` → 502 with structured body. Empty result → 200 with `{"items": []}`. |
| `GET /api/saved` | — | `{"items": [SavedItemDTO, ...]}` | Newest first. |
| `POST /api/saved` | `{"item": Item, "query": str}` | `SavedItemDTO` | Idempotent on `source_id`; 200 if created or already existed; 400 on malformed payload. |
| `DELETE /api/saved/{id}` | — | 204 / 404 | Cascades to `outputs`. |
| `POST /api/saved/{id}/caption` | — | `{"body": "...", "generated_at": "..."}` | Persists as `outputs` row. |
| `POST /api/saved/{id}/clip-prompt` | — | symmetric | — |
| `GET /api/saved/{id}/outputs?kind=caption\|clip_prompt` | — | `{"outputs": [...]}` | Newest first. |
| `GET /` (static) | — | HTML | Mounts `index.html` + linked assets. |
| `GET /health` | — | `{"status": "ok"}` | — |

- **CORS:** allow `http://localhost:*` only.
- **No auth** on the web UI (per D1).
- **Pydantic DTOs** separate from ORM models; explicit shape validated by pytest.
- **Smoke test** in `tests/test_api.py`: a single pytest that boots the app with an in-process transport + temp DB, hits every route end-to-end (search → save → list → caption → outputs → delete).

### Frontend (vanilla HTML/JS)

- Single `index.html` at static-files mount root, with linked `app.js` and `styles.css`.
- **Search bar at top.** Typing + Enter (or search button) calls `POST /api/search` and renders the result grid (thumbnail, product name, price, sold count, commission). "Save" toggle per row.
- **Saved items section** (panel below results, or simple tab toggle — pick one and document). Per item: the four fields compactly; "Generate caption" button; "Generate clip prompt" button; "Remove" button; on load, fetch existing outputs (`GET /api/saved/{id}/outputs?kind=...`) and display under the item so history is preserved across regenerations.
- **States:** explicit loading / empty / error for search and for save. Errors render a dismissible banner with the server-supplied message.
- **Idempotency** in the UI: double-click on "Save" produces exactly one row.
- Sensible default styling, readable on a laptop screen, no UI framework, no theme switcher.
- **Out of scope:** accessibility deep-dive (basic labels and keyboard focus only), mobile-first polish (laptop-localhost only), i18n.

### Operations (Makefile targets)

| Target | Purpose |
|--------|---------|
| `make run` | `uvicorn src.shopee_th.main:app --reload` on `localhost:8000` |
| `make test` | `pytest` (unit + e2e API tests, in-process) |
| `make lint` | `ruff check src tests` (or `flake8` if ruff not pinned) |
| `make e2e` | Boot `uvicorn` in the background, hit every API endpoint via `httpx` end-to-end against the real portal (gated on `SHOPEE_TH_E2E_COOKIE`; skip with explanatory `pytest.skip` and a clear console message if not set) |
| `make smoke` | Spin the app up against mock services (no network) and assert the page renders + the API responds OK — always-on |
| `make dev-reset` | Wipe `data/shopee_th.db` and `.env` (with confirmation prompt — never silently) |
| `make refresh-cookie` | `python scripts/refresh_cookie.py` — headed Chromium, log in interactively, persist cookies to `.env` |
| `make capture-affiliate-traffic` | `python scripts/capture_affiliate_traffic.py` — empirical Surface B capture to `docs/research/affiliate-observed-traffic.json` |

### Empirical discovery (Surface B)

`scripts/capture_affiliate_traffic.py` (invoked as `make capture-affiliate-traffic`):

- Opens a headed Chromium via Playwright to `https://affiliate.shopee.co.th/`.
- Waits for the user to log in interactively (reusing the same browser the cookie helper used would be ideal — same fingerprint, same cookie jar).
- Navigates to the portal's "search products" or "browse offers" page.
- Types a real, harmless search term (e.g. `iphone 15 case`).
- Attaches `page.on("request", ...)` and `page.on("response", ...)` listeners filtered to `affiliate.shopee.co.th` (and the resulting `Set-Cookie` headers).
- Writes a structured dump to `docs/research/affiliate-observed-traffic.json` — each entry: `{method, url, headers, post_data, status, response_headers, response_body_truncated}` (truncate bodies to ~4 KB; flag truncation in the entry).
- Stops after the user presses Enter in the terminal (or after a fixed 60 s window of typing).
- Idempotent: re-run overwrites the dump file.

Acceptance: `docs/research/affiliate-observed-traffic.json` exists, contains ≥3 distinct request types for the affiliate portal, and at least one matches the inferred GraphQL shape (`productOfferV2` or `product_search`-style query).

## Testing Decisions

**One primary e2e seam, three unit sub-seams.** The "ideal one seam" is the HTTP API; the sub-seams are existing abstractions in the codebase (Transport Protocol, repository against temp SQLite, OutputGenerator Protocol).

### Primary e2e seam: FastAPI HTTP layer via `httpx.AsyncClient`

- `tests/test_api.py` boots the FastAPI app with a `NoopTransport` (search) + temp `:memory:` SQLite (persistence) + `TemplateGenerator` (generation), in-process, and walks every route end-to-end:
  - `POST /api/search` with the NoopTransport returning a canned Surface A response → 200 with `{"items": [...]}`.
  - `POST /api/saved` with one of the items → 200 with `SavedItemDTO`.
  - `POST /api/saved` again with the same item (same `source_id`) → 200, same row id, no duplicate.
  - `GET /api/saved` → 1 item.
  - `POST /api/saved/{id}/caption` → 200 with non-empty `body`, total length ≤250.
  - `GET /api/saved/{id}/outputs?kind=caption` → 200 with 1 output.
  - `POST /api/saved/{id}/caption` again → 200; outputs now 2 (newest first).
  - `POST /api/saved/{id}/clip-prompt` → 200; `GET /api/saved/{id}/outputs?kind=clip_prompt` → 1 output.
  - `DELETE /api/saved/{id}` → 204; `GET /api/saved/{id}/outputs` → empty.
- Asserts the DTO shapes (Pydantic validation) and the error paths (`SearchError` → 502; bad payload → 400; missing `id` → 404).

### Sub-seam 1: `Transport` Protocol with `NoopTransport`

- `tests/test_search.py` uses `NoopTransport` to drive every branch of the search service:
  - Happy path (Surface A returns N items, Surface B returns commissions for a subset → output has commission filled where B succeeded, `null` elsewhere).
  - Empty result (Surface A returns `items: []` → `search()` returns `[]`, no exception).
  - Surface A → Surface B fusion with B raising `NotImplementedError` → A result still returned, commissions all `null`.
  - Surface A `error: 90309999` → `SearchError` with `code=90309999` and the offending URL attached.
  - Transient `error_msg` 200 → single retry succeeds, returns the second response.
  - 5xx → `SearchError` after one retry.
  - 10 s timeout → `SearchError` with timeout marker.

### Sub-seam 2: in-memory SQLite for the repository

- `tests/test_repository.py` runs the repository functions against a temp `:memory:` SQLite (or tmpfile) and asserts:
  - `save_item` round-trips and is idempotent on `source_id` (second call returns the same row, does not overwrite `payload`).
  - `list_saved` is newest-first.
  - `delete_saved` cascades to `outputs` (an `output` row referencing a deleted `saved_item` is gone).
  - `add_output` / `list_outputs` newest-first, no unique-constraint enforcement.
  - Malformed `payload` JSON is handled (load returns the row, but the JSON-blob is stored verbatim — DTO reconstruction is at the API layer).

### Sub-seam 3: `OutputGenerator` Protocol (templated stubs)

- `tests/test_generation.py` exercises the `TemplateGenerator` against multiple `Item` shapes:
  - Total caption length ≤250 for many seed inputs.
  - Hashtag count in `[4, 7]`.
  - Caption body contains the item title (or fallback).
  - Empty title → no exception, sensible placeholder.
  - Missing brand and missing category → no exception, generic hashtags.
  - Clip prompt is English, ≤300 chars, contains the title (or fallback).
  - `LLMGenerator()` raises `NotImplementedError` on either method.
  - `get_generator()` returns `TemplateGenerator` when `SHOPEE_TH_GENERATOR` is unset or `"stub"`; returns `LLMGenerator` when `"llm"`.

### E2E smoke: `make e2e`

- Boots `uvicorn` in the background.
- Hits every API endpoint via `httpx` end-to-end against the real portal.
- Uses a real cookie if `SHOPEE_TH_E2E_COOKIE` is set; otherwise skips with explanatory `pytest.skip` and a clear console message ("set SHOPEE_TH_E2E_COOKIE to run against live portal").
- Pass condition: every endpoint returns the documented shape and assertions hold.

### No-op smoke: `make smoke`

- Spins the app up against mock services (no network) and asserts the page renders + the API responds OK. Always-on; no env var required. This is the "the project boots from a clean clone" check.

### What makes a good test here

- **Test external behavior, not implementation details.** DTO shapes, error codes, route paths, idempotency contracts are the spec. Internal helper functions (e.g. `parseStoredHash` equivalents in this project) are tested only where they encode a non-obvious decision.
- **Pydantic DTOs are the contract.** Use `pydantic.TypeAdapter(Item).validate_python(...)` in tests to confirm the JSON shape end-to-end.
- **Each test sets up its own DB / transport / generator.** No shared mutable state across tests.
- **The e2e HTTP test is the canary.** If it passes, the API contract holds; if it fails, the integration broke.

### Prior art in the codebase

- `scripts/test-worker.mjs` in the sibling `todo-git-d` project is a good shape reference for `make smoke` (dependency-free, re-derives invariants, runs always-on). Not the same project, but the pattern is transferable: an independent re-derivation that asserts the contract from outside the app.

## Out of Scope

Ruled out for this iteration (redraw the destination before re-opening these):

- **Real LLM-backed caption / clip-prompt generation** — the `LLMGenerator` skeleton raises `NotImplementedError`. A follow-up map fills it in. Switching the env var to `llm` is the only change required at the call site.
- **Pagination UI and sort selector** on search results — default = first page, default relevance.
- **Multi-account / multi-locale** support.
- **Auto-refresh** of saved items' price/sold data.
- **Cloud / public deploy** — localhost-only by design.
- **Mobile-API reverse-engineering** as a first-class surface. Only widen if the empirical capture can't land an answer for Surface B.
- **Shopee Open API** — explicitly excluded by the destination itself.
- **Accessibility deep-dive** — basic labels and keyboard focus only; not WCAG-grade.
- **Mobile-first polish** — laptop-localhost only.
- **Internationalization** — UI is English with Thai caption outputs.
- **Hand-written SQL migrations** — `Base.metadata.create_all(engine)` is acceptable for v1.
- **Admin UI for listing / forcing logout of sessions** — out of scope; this is a personal tool.

## Further Notes

### In-scope fog (questions we expect, but can't phrase sharply yet)

- **Surface B (affiliate portal)** — exact endpoint URLs, GraphQL/REST shape, response JSON for a typical search. Becomes specifiable via `capture-affiliate-portal-traffic`.
- Whether the affiliate portal returns commission as a single `commissionRate` percent, or a richer `sellerCommissionRate` + `shopeeCommissionRate` + `commission` triple. Affects the `Item` Pydantic model and saved-items schema.
- Exact rate-limit numbers (anecdotal ≤1 req/s with backoff on `error: 90309999` is the working assumption).
- Login-time captcha: presence and form. Surfaces empirically from `implement-cookie-refresh-helper`.
- How the caption template should gracefully handle empty product titles or brand-less items.
- Cookie-expiry symptoms (HTTP status / body shape) and how to surface them in the UI.
- UX detail of "save": saved items in a separate tab/section, or inline with search results?

### Test seam decision (already approved)

- **Primary e2e seam:** FastAPI HTTP layer via `httpx.AsyncClient(app=app)` — every flow through the documented route table.
- **Unit sub-seams:** `NoopTransport` (search), in-memory SQLite (persistence), `OutputGenerator` Protocol (templated stubs).
- **E2E smoke seam:** the full app + real cookie via `make e2e` (env-gated; skip with clear message if no cookie).
- **No-op smoke:** `make smoke` against mocks (always-on; the "clean clone boots" check).

### Cross-references

- Destination and decisions: `.wayfinder/map.md`.
- Unit-of-work breakdown: `.wayfinder/tickets/` (10 tickets; 1 closed — `research-map-data-surfaces`).
- Surface A research output: `docs/research/data-surfaces.md`.
- Surface B empirical capture (pending): `docs/research/affiliate-observed-traffic.json`.

### How a session should pick up a ticket

A `wayfinder:*` session treats a single ticket's body as the unit of work and does not exceed it. The ticket lists `blocked_by` edges; a session should not start a ticket whose blockers are open. A session that completes a ticket updates the relevant `## Resolution` comment in the ticket body and appends a one-line entry under the map's `## Decisions so far` index.
