---
name: Shopee Affiliate TH — local app spec
labels: [wayfinder:spec, ready-for-agent]
status: draft
parent: map
created: 2026-07-16
tracker: local-markdown
---

# Spec: Shopee Affiliate TH — local app

This spec is synthesized from the wayfinder map (`.wayfinder/map.md`), the ten open tickets under `.wayfinder/tickets/`, and the research writeup at `docs/research/data-surfaces.md`. It captures the scope of the map in the standard spec shape so an agent picking up the work has one document to read end-to-end.

## Problem Statement

Shopee Affiliate Thailand affiliates want to research products and produce social-media copy + short-form video briefs for them, but the official Shopee Open Platform and the Affiliate OpenAPI both require partner credentials the user does not have, and the only practical data source is the affiliate portal itself. The current workflow is manual: open `shopee.co.th` in a browser, search for a product, copy the relevant fields by eye, switch to a notes app, and write a Thai caption by hand. That flow is slow, error-prone, impossible to reproduce across affiliate accounts, and offers no good way to keep a curated list of interesting products.

The user needs a **local-only** tool on their laptop that:

1. Searches Shopee Thailand for products by keyword.
2. Shows the four fields that matter for affiliate work — image, price, sold count, commission — for each result.
3. Lets the user save interesting items to a persistent local store.
4. For each saved item, generates a Thai caption (with English hashtags) and an English 8-second video clip prompt, ready to copy and paste into other tools.

Constraints: no official API key, no headless login, no public deployment, no login UI on the web app. Auth = a user-supplied browser session cookie. The generation step uses **templated stubs** (no LLM integration in this iteration) behind a clean interface ready to be swapped for a real LLM in a follow-up map.

## Solution

A local FastAPI web app, written in Python, served on `localhost:8000`, with a single-page HTML/JS frontend (vanilla JS, no build step). The backend calls Shopee's storefront hidden JSON API directly (with the user's `shopee.co.th` session cookie) for image/price/sold, and (optionally) the affiliate portal hidden JSON for commission. A Playwright cookie helper writes both the `shopee.co.th` and `affiliate.shopee.co.th` cookies into `.env` from a single headed browser session — cookies are bound to a browser fingerprint, and sharing across machines returns error `90309999`, so the helper and the searcher must use the same Chromium. The caption/clip-prompt step is a `TemplateGenerator` behind a `Protocol` interface, ready to be swapped for a real LLM later. The whole app is local, single-user, no auth UI.

## User Stories

1. As an affiliate researcher, I want to type a product keyword into a search bar, so that I can find matching products on Shopee Thailand without leaving the app.
2. As a user, I want search results to show product image, price, sold count, and commission, so that I can quickly evaluate which items are worth promoting.
3. As a user, I want results to render in a clean grid, so that I can scan many items at once.
4. As a user, I want pressing Enter (or a search button) to trigger a search, so that I don't have to leave the keyboard.
5. As a user, I want search results to replace previous results (not accumulate), so that the screen stays uncluttered.
6. As a user, I want to save an item with one click, so that I can come back to it later.
7. As a user, I want saved items to persist across app restarts, so that my work isn't lost.
8. As a user, I want to see all my saved items in a separate panel, so that I can review what I've collected.
9. As a user, I want a "Generate caption" button per saved item, so that I can get a Thai-language social caption without writing one myself.
10. As a user, I want a "Generate clip prompt" button per saved item, so that I can get an English 8-second video brief for a creator.
11. As a user, I want generated captions to be Thai + English hashtags, ≤ 250 chars total, so that they fit common social platforms.
12. As a user, I want generated clip prompts to be in English and ≤ ~300 chars, so that they fit typical "shot list" inputs.
13. As a user, I want caption and clip-prompt generation to handle empty/missing product fields gracefully, so that the app never crashes on a thin product listing.
14. As a user, I want a "Copy to clipboard" button on each generated output, so that I can paste it into another tool in one click.
15. As a user, I want prior generated outputs to be visible per saved item, so that I can see the history of what I generated.
16. As a user, I want to regenerate an output (re-click "Generate caption"), so that I can get a fresh version without losing the old one.
17. As a user, I want to delete a saved item, so that I can keep the saved list curated.
18. As a user, I want explicit loading / empty / error states for search and for save, so that I can tell whether the app is working.
19. As a user, I want errors to show the server-supplied message in a dismissible banner, so that I can see what went wrong without digging in logs.
20. As a user, I want the saved-items save action to be idempotent, so that double-clicking doesn't create duplicates.
21. As a user, I want the UI to never display a "saving…" state forever, so that a hung request doesn't lock up the panel.
22. As a developer setting up the app for the first time, I want a single `make refresh-cookie` command that opens a browser, lets me log in interactively, and writes both cookies to `.env`, so that I don't have to copy cookies by hand.
23. As a developer, I want the cookie helper to log into both `shopee.co.th` and `affiliate.shopee.co.th` in the same browser, so that both surfaces share a fingerprint.
24. As a developer, I want `make run` to boot the app locally, so that I can open the UI in a browser immediately.
25. As a developer, I want `make test` to run unit and integration tests, so that I can verify changes don't break anything.
26. As a developer, I want `make e2e` to drive the full API end-to-end with a real cookie, so that I can confirm the live portal still works.
27. As a developer, I want `make smoke` to spin the app up against mock services (no network), so that I can verify the page renders without a real cookie.
28. As a developer, I want `make dev-reset` to wipe the local DB and `.env` (with confirmation), so that I can start over cleanly.
29. As a developer, I want a `make capture-affiliate-traffic` command that opens the affiliate portal and dumps the hidden JSON traffic to disk, so that I can refresh the empirical contract for the commission leg.
30. As a developer, I want a `make lint` target, so that I can keep the codebase clean.
31. As a maintainer, I want a clear README with prereqs, first-time setup, run, use, and troubleshoot sections, so that I can hand the project to a new contributor.
32. As a maintainer, I want the search service to use a `Transport` protocol with two impls (production and test-only), so that unit tests don't hit the network.
33. As a maintainer, I want the generator to expose a `Protocol` interface, so that swapping the templated stub for a real LLM is a one-class change.
34. As a maintainer, I want the SQLAlchemy ORM models to be separate from the Pydantic API DTOs, so that the API contract can evolve independently of storage.
35. As a maintainer, I want the empirical affiliate-portal traffic dump to live in the repo at a known path, so that the contract for the commission leg has a single source of truth.
36. As a maintainer, I want errors from the search service to carry the offending URL and Shopee's `error` code, so that debugging cookie-expiry or rate-limit issues is straightforward.

## Implementation Decisions

### Stack and project layout

- **Language / runtime:** Python ≥ 3.11.
- **Package manager:** `uv`. `uv sync` produces a lockfile.
- **Web framework:** FastAPI, served by `uvicorn[standard]`.
- **Async HTTP client:** `httpx` for both surfaces.
- **Browser automation:** Playwright (Python), used by the cookie-refresh helper and the affiliate-traffic capture script.
- **DB:** SQLite, file at `data/shopee_th.db`, accessed via SQLAlchemy 2.x.
- **Config:** `pydantic-settings`, reading `.env`.
- **Tests:** `pytest`, `pytest-asyncio`, `httpx.AsyncClient(app=app)` for API integration tests.
- **Project layout** (high level — see wayfinder map for ticket-level breakdown):
  - Source under `src/shopee_th/`, with subpackages `api/`, `services/`, `models/`, `templates/`.
  - Top-level `scripts/`, `tests/`, `docs/`, `Makefile`, `pyproject.toml`, `README.md`, `.env.example`, `.gitignore`.

### Data model (Storage)

- **`saved_items`** table:
  - `id` — autoincrement integer primary key.
  - `query` — text, the search string the user typed when saving.
  - `source_id` — text, Shopee's product id (item id). **UNIQUE** constraint, so save is idempotent.
  - `payload` — JSON-blob text, the full `Item` captured at save time (so we never lose upstream fields).
  - `saved_at` — timestamp, default `now()`.
- **`outputs`** table:
  - `id` — autoincrement integer primary key.
  - `saved_item_id` — integer foreign key → `saved_items.id`, `ON DELETE CASCADE`.
  - `kind` — text, one of `'caption' | 'clip_prompt'`, indexed together with `saved_item_id`.
  - `body` — text, the generated output.
  - `generated_at` — timestamp, default `now()`.
  - No unique constraint — history is preserved across regenerations.
- **Migration:** first-run `Base.metadata.create_all(engine)` is acceptable for v1.
- **Repository functions** (async): `save_item` (idempotent on `source_id`, never overwrites the payload), `list_saved` (newest first), `get_saved`, `delete_saved` (cascades to outputs), `add_output`, `list_outputs` (newest first).
- **DTOs:** Pydantic models for the API contract, separate from ORM models.

### Search service (Surface A and B)

- Single module exposing `async def search(query: str, limit: int = 20) -> list[Item]`.
- `Item` is a Pydantic model with the four promoted fields (`image`, `price`, `sold`, `commission`) and a `raw: dict` field for the full upstream payload (persisted in `saved_items.payload`).

**Surface A — `shopee.co.th/api/v4` (contract closed in research):**

- Endpoint: `GET https://shopee.co.th/api/v4/search/search_items`.
- Required headers (one-line each):
  - `User-Agent` — a desktop Chrome UA string from the same browser that produced the cookie.
  - `cookie` — `SHOPEE_TH_SESSION_COOKIE` from `.env`.
  - `referer: https://shopee.co.th/`.
  - `x-api-source: pc` (required).
  - `af-ac-enc-dat: null` (required — the load-bearing trick. Without it, every call returns `error: 90309999` regardless of cookie quality).
- Query params: `by=relevancy`, `limit` (≤ 20 for the API, ≤ 60 for direct curl), `keyword`, `newest=0` (offset), `order=desc`, `page_type=search`, `scenario=PAGE_SEARCH`, `version=2`.
- Field extraction:
  - `image` ← `items[i].item_basic.image`, prefix `https://cf.shopee.co.th/file/`.
  - `price` ← round(`items[i].item_basic.price` / 100000) in THB. Use `price_min` if `price` looks IP-tampered.
  - `sold` ← `items[i].item_basic.historical_sold`.

**Surface B — `affiliate.shopee.co.th` (empirical — contract pending):**

- Endpoint: TBD. Expected family: `POST https://affiliate.shopee.co.th/graphql` or similar REST endpoint. Empirical capture lives at `docs/research/affiliate-observed-traffic.json` and is regenerated by `make capture-affiliate-traffic`.
- Auth cookie: `SHOPEE_TH_AFFILIATE_COOKIE`.
- Expected fields per item: `commissionRate` (e.g. `"0.06"` = 6 %), `sellerCommissionRate`, `shopeeCommissionRate`, `commission` (= price × rate), `sales`/`sold`, `priceMin`/`priceMax`, `productName`, `shopName`, `imageUrl` (full URL, no `cf.shopee.co.th/file/` prefix).
- Until the empirical capture ticket lands, **the affiliate leg is best-effort**: the function signature accepts `affiliate_leg: bool = True`; if Surface B raises or returns no data, Surface A results are still returned and `Item.commission` stays `null`. No exception propagates from the commission phase alone.

**Two-leg merge contract:**

- `search()` calls Surface A first, builds `Item` rows with image/price/sold.
- If `affiliate_leg=True` and Surface B is callable, fill `commission` per item keyed by `itemId` (or `shopid`+`itemid`).
- If the affiliate leg raises `NotImplementedError` or returns no data, the function still returns the Surface A rows.

**Robustness:**

- `httpx.AsyncClient` with 10 s timeout.
- Single retry with linear backoff for `error_msg`-bearing 200s.
- `error: 90309999` is a hard failure (cookie-bound, retrying is pointless) — raise `SearchError` with a message guiding the user to `make refresh-cookie`.
- Treat response as empty (`[]`) when `items` is missing/empty. Never raise on no result.
- `SearchError(str)` for upstream failures, with the offending URL and the `error` code from Shopee attached as attributes.
- **Mockability:** every Shopee call goes through a thin `Transport` protocol with two impls (`HttpTransport` for production, `NoopTransport` for tests). The search service has no FastAPI / app-config imports.

### Cookie refresh helper

- Single script, invoked as `make refresh-cookie`.
- Opens a real headed Chromium via Playwright.
- Visits `shopee.co.th` first, then `affiliate.shopee.co.th` — affiliate-portal cookies are issued under the second origin and may include a portal-specific value (e.g. `SPC_IA` / `affiliate_id`-style).
- User logs in interactively to both surfaces when prompted; the script waits for the post-login signal that the portal landing page is reachable.
- Extracts and persists:
  - `SHOPEE_TH_SESSION_COOKIE` — the `; `-joined cookie string for `shopee.co.th` (Surface A).
  - `SHOPEE_TH_AFFILIATE_COOKIE` — the `; `-joined cookie string for `affiliate.shopee.co.th` (Surface B).
  - `SHOPEE_TH_AFFILIATE_ID` — set to `""` for now; will be filled by the empirical capture ticket if needed.
- Writes to `.env`, overwriting in place.
- Idempotent on re-run; non-zero exit on timeout / post-login signal failure.
- Cookies come from the same Chromium the helper launched — Shopee binds `SPC_*` to a browser fingerprint and reused cookies from another process fail with `error: 90309999`. The helper must not attempt to harvest cookies via any other browser.

### Affiliate traffic capture (one-shot empirical)

- Single script, invoked as `make capture-affiliate-traffic`. Output: `docs/research/affiliate-observed-traffic.json`.
- Opens a headed Chromium via Playwright to `https://affiliate.shopee.co.th/`.
- Waits for the user to log in interactively (same browser fingerprint as the cookie helper would produce).
- Navigates to the portal's search/browse page, types a real, harmless term (e.g. `iphone 15 case`).
- Subscribes to `page.on("request", ...)` and `page.on("response", ...)` filtered to `affiliate.shopee.co.th` and `Set-Cookie` headers.
- Writes each entry as `{method, url, headers, post_data, status, response_headers, response_body_truncated}` (bodies truncated to ~4 KB; flag truncation in the entry).
- Stops after the user presses Enter in the terminal (or after a 60 s typing window).
- Idempotent: re-run overwrites the dump file.
- Acceptance: file exists, contains ≥ 3 distinct request types, at least one matches an inferred GraphQL shape (`productOfferV2` or `product_search`-style).

### Generation (caption + clip prompt)

- Module exposes a `Protocol` interface with two methods: `caption(item) -> str` and `clip_prompt(item) -> str`.
- Default `TemplateGenerator` (selected when `SHOPEE_TH_GENERATOR=stub`, the default):
  - **Caption:** Thai body ≤ 180 chars, drawing from `item.title`, `item.brand` (if present), price, sold count (rendered as `ขายแล้ว X ชิ้น` or similar natural Thai). 4–7 English hashtags appended, chosen deterministically (`#ShopeeTH #<category-slug> #<price-band>` + 2 derived from the item). Total `len(caption)` ≤ 250. Truncate body first, then drop lowest-priority hashtags if still over.
  - **Clip prompt:** 1–2 sentence English brief for an 8-second vertical video, e.g. `"Vertical 9:16, 8s, hand-held close-up of {title} on a clean surface, upbeat Thai-market styling, ..."`. ≤ 300 chars.
  - Both handle empty title, missing brand, missing category gracefully (no exceptions; produce a useful placeholder).
- A no-op `LLMGenerator` skeleton class that raises `NotImplementedError` on every call — explicit slot for the follow-up map.
- Factory `get_generator() -> OutputGenerator` reads `SHOPEE_TH_GENERATOR` from env.

### HTTP layer

- Routes:
  - `POST /api/search` — body `{query, limit?}`, cap limit at 20. `SearchError` → 502 with structured body; empty result → 200 with `{"items": []}`.
  - `GET /api/saved` — newest first.
  - `POST /api/saved` — body `{item, query}`, idempotent on `source_id`. 200 if created or already existed; 400 on malformed payload.
  - `DELETE /api/saved/{id}` — 204 on success, 404 if missing. Cascades to outputs.
  - `POST /api/saved/{id}/caption` — calls generator, persists, returns `{body, generated_at}`.
  - `POST /api/saved/{id}/clip-prompt` — symmetric.
  - `GET /api/saved/{id}/outputs?kind=caption|clip_prompt` — newest first.
  - Static-files mount at `/` (placeholder mount OK; frontend lives in a separate ticket).
- CORS: `http://localhost:*` only. No auth.
- Pydantic request/response DTOs separate from ORM models.

### Frontend

- Single self-contained HTML + CSS + JS page, served from the static mount. Vanilla JS — no React/Vue/build step.
- Search bar at top → `POST /api/search` → grid of result cards.
- Per-row **Save** toggle (idempotent server-side, double-click safe in UI).
- Saved items panel (separate panel or simple tab toggle) with per-item:
  - Compact view of the four fields.
  - **Generate caption** + **Generate clip prompt** buttons.
  - Existing outputs (`GET /api/saved/{id}/outputs?kind=...`) rendered read-only with a **Copy to clipboard** button.
  - **Remove** button → `DELETE /api/saved/{id}`.
- Explicit loading / empty / error states for search and for save. Errors render a dismissible banner with the server-supplied message; never silently swallowed.
- Sensible default styling for a laptop screen. No UI framework, no theme switcher.
- Out of scope: deep accessibility, mobile-first polish, i18n.

### Tooling

- `Makefile` (or `taskfile.yml`) with:
  - `make run` — `uvicorn` with reload.
  - `make refresh-cookie` — the Playwright helper.
  - `make capture-affiliate-traffic` — Playwright capture script → `docs/research/affiliate-observed-traffic.json`.
  - `make test` — unit + integration.
  - `make lint` — linter.
  - `make e2e` — boots `uvicorn` in the background, drives every API endpoint end-to-end with `httpx`. Uses a real cookie if `SHOPEE_TH_E2E_COOKIE` is set; otherwise `pytest.skip`s with a clear message.
  - `make smoke` — boots the app against mock services (no network), asserts the page renders + the API responds OK. Always-on; no env var required.
  - `make dev-reset` — wipes `data/shopee_th.db` and `.env`, with confirmation prompt (never silent).

### Configuration

- `.env` keys:
  - `SHOPEE_TH_SESSION_COOKIE` — `; `-joined cookie string for `shopee.co.th`.
  - `SHOPEE_TH_AFFILIATE_COOKIE` — `; `-joined cookie string for `affiliate.shopee.co.th`.
  - `SHOPEE_TH_AFFILIATE_ID` — placeholder, default `""`.
  - `SHOPEE_TH_GENERATOR` — `stub` (default) | `llm` (raises `NotImplementedError` in this map; wired for follow-up).
  - `SHOPEE_TH_AFFILIATE_TRANSPORT` — `http` (default; best-effort) | `playwright` (fallback when the JSON endpoint isn't reliably callable).
  - `SHOPEE_TH_E2E_COOKIE` — optional; if set, `make e2e` runs against the live portal.
- `.env.example` ships with all keys, no real values.

### Empirical contract (Surface B)

- The affiliate-portal surface's endpoint URL, headers, request body, and response shape live in `docs/research/affiliate-observed-traffic.json`, regenerated by `make capture-affiliate-traffic`.
- The Surface B leg in the search service is treated as a contract test against this dump — when the file is current, the leg is "verified"; when stale, it's "best-effort."

## Testing Decisions

- **Test external behavior, not implementation details.** A test that asserts the API returns `{items: [...]}` with the four fields is good. A test that asserts an internal helper was called is not.
- **Single highest seam: the FastAPI HTTP API.** One end-to-end test that boots the app with an in-process `Transport` + temp DB and drives `search → save → list → caption → outputs → clip-prompt → outputs → delete` via `httpx.AsyncClient(app=app)` proves the whole stack.
- **Lower seams for unit-level coverage:**
  - **Search service:** 3–5 unit tests with `NoopTransport` — success path, empty result, two-leg fusion (A returns N items, B returns commissions for a subset, output has commission filled where B succeeded and `null` elsewhere), Surface B unavailable (B raises, A result still returned).
  - **Generation:** tests for caption ≤ 250 chars across many seed inputs, hashtag count ∈ [4, 7], body contains title (or fallback), empty-title → no exception + sensible placeholder, clip prompt English + ≤ 300 chars + contains title.
  - **Repository:** integration test against `:memory:` (or tmp-file) sqlite for round-trip + idempotency on save.
- **Live portal coverage:** `make e2e` is the single opt-in live-coverage gate. It uses `SHOPEE_TH_E2E_COOKIE` if set; otherwise it `pytest.skip`s with a clear console message.

## Out of Scope

- **Real LLM-backed caption / clip-prompt generation.** Deferred to a follow-up map. This map ships templated stubs only and explicitly leaves a `Protocol` slot for `LLMGenerator`.
- **Pagination UI and sort selector** on search results. Default = first page, default relevance.
- **Multi-account / multi-locale** support.
- **Auto-refresh** of saved items' price/sold data.
- **Cloud / public deploy.** Localhost-only by design.
- **Mobile-API reverse-engineering** as a first-class surface. Only widen if Surface A/B can't land the answer.
- **Shopee Open API** (Surface C / D). Explicitly excluded by the destination itself.

## Further Notes

- **Single source of truth for the empirical Surface B contract:** `docs/research/affiliate-observed-traffic.json`. When the search-service Surface B leg changes, the dump file is the spec it should be tested against.
- **Cookie expiry symptoms are surface-specific and observed by the user:** an `error: 90309999` from the search service almost always means the cookie is dead (or it came from a different browser). The `make refresh-cookie` remedy is the first thing the README's Troubleshoot section should point at.
- **Open questions that will sharpen into tickets as the frontier advances:**
  - Whether the affiliate portal returns commission as a single `commissionRate` percent, or a richer `sellerCommissionRate` + `shopeeCommissionRate` + `commission` triple. Affects the `Item` Pydantic model and the saved-items schema.
  - Whether the affiliate-portal search offers sold count as `historical_sold` (matches storefront) or as a different field. Affects whether we display two numbers.
  - Concrete rate-limit thresholds (the working assumption is ≤ 1 req/s with jittered delays; pinning this empirically is a one-off script task).
  - Login-time captcha presence on the affiliate portal. The cookie helper will surface this empirically; if a captcha always appears, add a manual-entry fallback in the helper.
  - UX detail of "save": saved items in a separate tab/section, or inline with search results? — left to the frontend ticket, default = separate panel.
