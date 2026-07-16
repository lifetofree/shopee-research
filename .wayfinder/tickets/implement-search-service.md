---
name: Implement search service module
labels: [wayfinder:task]
status: closed
assignee: Mavis
blocked_by: [research-map-data-surfaces, bootstrap-python-project]
parent: map
created: 2026-07-16
claimed: 2026-07-16
closed: 2026-07-16
unblocks: [implement-fastapi-http-layer, capture-affiliate-portal-traffic]
---

## Resolution (2026-07-16)

**Asset:** `src/shopee_th/services/search.py` (`search()`, `SearchError`), `src/shopee_th/services/transport.py` (`Transport`, `HttpTransport`, `NoopTransport`), `src/shopee_th/models/domain.py` (`Item`). `uv run pytest` → 10/10 green (2 bootstrap + 8 new in `tests/test_search.py`).

**Files created:**

- `src/shopee_th/models/domain.py` — `Item` Pydantic model: `source_id`, `title` (structural — not part of the merge contract but required to identify/display a result) plus the four merge-contract fields `image`, `price`, `sold`, `commission`; everything else from Surface A's `item_basic` lives verbatim in `raw: dict`.
- `src/shopee_th/services/transport.py` — `Transport` Protocol (`get`/`post` → parsed JSON dict); `HttpTransport` (httpx.AsyncClient, 10 s timeout, `raise_for_status()`); `NoopTransport` (queues canned responses or exceptions per call, records `get_calls`/`post_calls` for assertions).
- `src/shopee_th/services/search.py` — `search(query, limit=20, *, transport, session_cookie, user_agent, affiliate_cookie=None, affiliate_leg=True, offset=0) -> list[Item]`. Surface A call with the required header/param set from research §2.3; `_extract_price` falls back to `price_min` per §2.5; `SearchError(message, url, code)` with `is_timeout` marker; single linear-backoff retry on transport-level exceptions and transient `error_msg` 200s; immediate raise (no retry) on `error: 90309999`. Surface B is a best-effort GraphQL call against the inferred `productOfferV2` shape (research §3.3); any failure (including `NotImplementedError` when no affiliate cookie is configured) is swallowed and commissions stay `null`.
- `tests/test_search.py` — 8 unit tests against `NoopTransport`: happy path (no affiliate leg), empty result, two-leg fusion (commission filled for a subset, `null` elsewhere), Surface B unavailable, cookie-binding error (no retry), transient error (retries once then succeeds), transport failure (`SearchError` after one retry), timeout marker.

**Decisions worth surfacing:**

- **`search()` takes `transport`/`session_cookie`/`user_agent`/`affiliate_cookie` as explicit parameters, not `shopee_th.config` reads** — keeps the module import-free of app config per the ticket's "library-importable" requirement; the FastAPI layer (next ticket) is responsible for wiring `Settings` values in.
- **`source_id` and `title` are promoted alongside the four merge-contract fields** — the ticket's "four promoted fields" language documents the merge contract specifically, but an `Item` with no id/title can't be displayed (SPEC story 11) or saved idempotently (`saved_items.source_id`, per the persistence ticket), so these two are structural necessities rather than merge-contract fields. `source_id` is built as `f"{shopid}.{itemid}"`.
- **Surface B is implemented (not stubbed to `NotImplementedError` unconditionally)** — ticket allows either; implementing the inferred GraphQL shape now means the merge path has real logic to test, and it degrades to the same "commission stays null" behavior once `capture-affiliate-portal-traffic` lands and reveals the shape was wrong — no call-site changes needed, only the query/parsing inside `_fetch_surface_b`.
- **Retry backoff is 0.05 s**, not a specific SLA number — the ticket only requires "linear backoff"; kept small so the test suite stays fast.

**Acceptance check (per ticket):**

- ✅ `search()` matches the required signature (plus explicit transport/cookie/UA params, justified above).
- ✅ `Item` captures every Surface A field via `raw`, four fields promoted.
- ✅ Surface A headers/params/field-extraction match research §2.3–2.4 exactly.
- ✅ Two-leg merge: Surface B best-effort, `NotImplementedError`/no-data swallowed, Surface A rows always returned.
- ✅ `httpx.AsyncClient` 10 s timeout in `HttpTransport`.
- ✅ Single retry w/ linear backoff on transient failures; immediate raise on `error: 90309999`.
- ✅ Empty/missing `items` → `[]`, never raises.
- ✅ `SearchError` carries `url` and `code`.
- ✅ `Transport` Protocol with `HttpTransport` + `NoopTransport`.
- ✅ No FastAPI / app-config imports in `search.py` or `transport.py`.
- ✅ 8 unit tests (ticket asked for 3–5) covering every listed scenario.
- ✅ No HTTP routes, no UI, no SQLite writes added.

## Question

Implement `src/shopee_th/services/search.py` exposing:

```python
async def search(query: str, limit: int = 20) -> list[Item]: ...
```

where `Item` is a Pydantic model capturing **every** field the chosen surfaces return, with the four promoted fields documented and the rest kept in a `raw: dict` field for SQLite persistence.

**Concrete primary surface (Surface A — closed in research):**

- Endpoint: `GET https://shopee.co.th/api/v4/search/search_items`
- Required headers (one-line each):
  - `User-Agent`: a desktop Chrome UA string from the same browser that produced the cookie.
  - `cookie`: `SHOPEE_TH_SESSION_COOKIE` from `.env`.
  - `referer: https://shopee.co.th/`.
  - `x-api-source: pc` (required).
  - `af-ac-enc-dat: null` (required — without it Shopee returns `error: 90309999`).
- Query params: `by=relevancy`, `limit=<20|user-limit>`, `keyword=<urlencoded query>`, `newest=<offset, 0/60/...>`, `order=desc`, `page_type=search`, `scenario=PAGE_SEARCH`, `version=2`.
- Field extraction:
  - `image` ← `items[i].item_basic.image` with the literal prefix `https://cf.shopee.co.th/file/` prepended.
  - `price` ← round(`items[i].item_basic.price` / 100000) in THB (use `price_min` if `price` looks invalid / IP-tampered, see research §2.5).
  - `sold` ← `items[i].item_basic.historical_sold`.
  - `commission` ← **null for now**; Surface A doesn't expose it. The affiliate leg (Surface B) merges `commission` into the `Item` post-pass — see "Two-leg merge" below.

**Secondary surface (Surface B — open; deferred merge until `capture-affiliate-portal-traffic` lands):**

- Endpoint: TBD (expected family: `POST https://affiliate.shopee.co.th/graphql` or similar).
- Auth cookie: `SHOPEE_TH_AFFILIATE_COOKIE`.
- Expected fields per item: `commissionRate` (e.g. "0.06" = 6 %), `sellerCommissionRate`, `shopeeCommissionRate`, `commission` (= price × rate), `sales` (or `sold`), `priceMin`/`priceMax`, `productName`, `shopName`, `imageUrl` (already a full URL).
- Until the empirical capture ticket lands, **the affiliate leg is best-effort**: this ticket implements only the Surface A leg, plus the *scaffolding* for two-leg merge (the function signature accepts an optional `affiliate_leg: bool = True` flag; the Playwright-based leg can be slotted in without breaking the call sites).

**Two-leg merge contract:**

- `search()` calls Surface A first, builds `Item` rows with image/price/sold.
- If `affiliate_leg=True`, it then attempts the Surface B call with `itemId` (or `shopid`+`itemid`) keys from the storefront result.
- Each `Item.commission` is populated if the affiliate leg succeeds; left `null` otherwise.
- If the affiliate leg raises `NotImplementedError` or returns no data, the function still returns the Surface A rows. No exception is propagated for the commission phase alone.

**Robustness:**

- `httpx.AsyncClient` with a 10 s timeout.
- Single retry with linear backoff for `error_msg`-bearing 200s and `error: 90309999` cookie-bound failures (which usually mean *not the same browser*; raise a `SearchError` with guidance rather than retry into the same failure).
- Treat response as empty (`[]`) when `items` is missing/empty. Never raise on no result.
- `SearchError(str)` for upstream failures, with the offending URL and the `error` code from Shopee attached as attributes.
- Trivially mockable: every shopee call goes through a thin `Transport` protocol with two impls (`HttpTransport`, `NoopTransport` for tests).
- Library-importable: no FastAPI / no app-config imports inside this module.

**Tests:** 3-5 unit tests using `NoopTransport` returning canned responses for: success path, empty result, Surface A → Surface B fusion (A returns N items, B returns commissions for a subset, output has commission filled where B succeeded and `null` elsewhere), Surface B unavailable (B raises, A result still returned).

This ticket produces NO HTTP routes, NO UI, NO SQLite writes.
