---
name: Shopee Affiliate TH data via local web app
labels: [wayfinder:map]
status: open
created: 2026-07-16
tracker: local-markdown
---

# Shopee Affiliate TH data via local web app

## Destination

A local FastAPI web app (Python) on `localhost`, single-page HTML/JS UI, authenticating to Shopee Affiliate Thailand via a user-supplied session cookie stored in `.env`. The user types a product name into the UI; the app searches the affiliate portal and renders matching products (image, commission, price, sold). The user can select items and save them to a persistent SQLite store, and per saved item generate a Thai-language caption + English-hashtag summary (≤250 chars total) plus an English 8-second clip prompt. This map ships those generation buttons backed by **templated stubs** behind a clean interface ready to swap in an LLM later.

## Notes

- **Tracker**: local-markdown (`.wayfinder/` folder, no remote issue tracker configured).
- **Domain**: Web scraping / affiliate data extraction / personal tooling.
- **Stack pinned**: Python, FastAPI, SQLite (SQLAlchemy 2.x), Playwright (Python — for cookie helper, possibly fallback transport), httpx for HTTP, uv for env management, uvicorn to run, pydantic-settings for config.
- **Conventions**:
  - Don't use the Shopee Open API (out of scope by definition — destination explicitly says "without Shopee open API").
  - Auth = single replayed session cookie via `.env`. No headless login flow beyond the helper script.
  - Localhost only. No auth on the web UI itself (per D1).
  - Every `wayfinder:*` session treats a single ticket's body as the unit of work and does not exceed it.
- **Skills to consult while resolving tickets**: web-search, prototype (for any throwaway UI), grilling / domain-modeling when scope flickers.

## Decisions so far

<!-- index — one line per closed ticket. Append as tickets close. -->

- [Research — Map the available Shopee Affiliate TH data surfaces](.wayfinder/tickets/research-map-data-surfaces.md) — `shopee.co.th/api/v4/search/search_items` is the primary surface (image/price/sold via `http`), with mandatory `af-ac-enc-dat: null` + `x-api-source: pc` headers and price divisor 100000; commission must come from `affiliate.shopee.co.th` (Surface B), whose JSON contract is still empirical — captured by the `capture-affiliate-portal-traffic` ticket, written up at [`docs/research/data-surfaces.md`](../../docs/research/data-surfaces.md).
- [Bootstrap — Scaffold the Python project](.wayfinder/tickets/bootstrap-python-project.md) — `uv` + hatchling + `pyproject.toml`; FastAPI/uvicorn/SQLAlchemy[asyncio]/aiosqlite/pydantic/pydantic-settings/python-dotenv/httpx/playwright as runtime; pytest/pytest-asyncio under `[project.optional-dependencies].dev`. `src/shopee_th/main.py:create_app()` factory + module-level `app`; `/` and `/health` return `StatusResponse(status, version)`. `Settings` (pydantic-settings) is all-optional with safe defaults. `Makefile` wires `install`, `run`, `test`, `lint`, `e2e` (env-gated skip-with-message), `smoke`, `dev-reset` (with prompt), and `refresh-cookie`/`capture-affiliate-traffic` as TODO stubs. Pytest 2/2 green. `unblocks` all four downstream tickets that depend on a runnable project.
- [Spec — Synthesize map + tickets into a single spec](.wayfinder/spec.md) — `ready-for-agent`. One FastAPI HTTP API seam (search → save → list → caption → outputs → clip-prompt → delete via `httpx.AsyncClient(app=app)`); lower seams for unit-level coverage; `docs/research/affiliate-observed-traffic.json` is the empirical contract test target for the Surface B leg.
- [Implement search service module](.wayfinder/tickets/implement-search-service.md) — `src/shopee_th/services/search.py` (`search()`, `SearchError`) + `services/transport.py` (`Transport`/`HttpTransport`/`NoopTransport`) + `models/domain.py` (`Item`). Surface A implemented per research; Surface B implemented best-effort against the inferred `productOfferV2` GraphQL shape (still unconfirmed pending `capture-affiliate-portal-traffic`), swallowed on any failure so commissions default to `null`. 8/8 new unit tests green. `unblocks` `implement-fastapi-http-layer`.

## Not yet specified

In-scope fog — questions we expect, but can't phrase sharply yet:

- **Surface B (affiliate portal)** — exact endpoint URLs, GraphQL/REST shape, response JSON for a typical search. Becomes specifiable via [`capture-affiliate-portal-traffic`](tickets/capture-affiliate-portal-traffic.md) which is now an open ticket.
- Whether the affiliate portal returns commission as a single `commissionRate` percent, or a richer `sellerCommissionRate` + `shopeeCommissionRate` + `commission` triple. Affects the `Item` Pydantic model and saved-items schema.
- Exact rate-limit numbers (anecdotal ≤1 req/s with backoff on `error: 90309999` is the working assumption).
- Login-time captcha: presence and form. Surfaces empirically from `implement-cookie-refresh-helper`.
- How the caption template should gracefully handle empty product titles or brand-less items.
- Cookie-expiry symptoms (HTTP status / body shape) and how to surface them in the UI.
- UX detail of "save": saved items in a separate tab/section, or inline with search results?

## Out of scope

Ruled out for this effort (redraw the destination before re-opening these):

- **Real LLM-backed caption / clip-prompt generation** — deferred to a follow-up map. This map ships templated stubs only.
- **Pagination UI and sort selector** on search results — deferred (default = first page, default relevance per J1).
- **Multi-account / multi-locale** support.
- **Auto-refresh** of saved items' price/sold data.
- **Cloud / public deploy** — localhost-only by design (per D1).
- **Mobile-API reverse-engineering** as a first-class surface (assumed; only widen if research can't land an answer).
- **Shopee Open API** — explicitly excluded by the destination itself.
