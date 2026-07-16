# Shopee Affiliate TH — data surfaces research

**Author:** droid (Wayfinder research ticket `research-map-data-surfaces`)
**Date:** 2026-07-16
**Scope:** identify surfaces we can hit *without* the Shopee Open Platform API (open.shopee.com) and *without* the Shopee Affiliate GraphQL OpenAPI, given only a user-supplied browser session cookie for `affiliate.shopee.co.th`. Enumerate endpoints, headers, response shapes, and pick a transport.

> The user has not granted access to a real affiliate account, so parts of this write-up that touch the affiliate portal internals are **inference from public docs** and labeled as such. Where actual evidence (DevTools, signed-in browser) is needed, the empirical step is called out explicitly so it can be performed by the user in a follow-up session (or by the Playwright cookie helper itself).

---

## 1. Surface inventory

| ID | Surface | Auth | Has commission? | Status |
|----|---------|------|------------------|--------|
| A | Public storefront hidden JSON (`shopee.co.th/api/v4`) | Light (browser cookies) | No | Verifiable from public sources; this is the path of least friction for image / price / sold. |
| B | Affiliate portal hidden JSON (`affiliate.shopee.co.th` SPA backend) | Required (user cookie) | Yes (per item) | Endpoints not publicly documented; needs DevTools capture during a real signed-in session. |
| C | Shopee Affiliate **GraphQL OpenAPI** at `open-api.affiliate.shopee.th/graphql` | OAuth + HMAC `app_id`/`secret`/`Authorization: SHA256Credential=…, Signature=…` | Yes | Out of scope: requires official credentials, which the destination forbids ("without Shopee open API"). Listed here only for completeness / to prevent confusion with Surface B. |
| D | Shopee Open Platform (`open.shopee.com`) | OAuth + partner keys | No | Out of scope: explicitly excluded by the destination. |

**Recommendation (one-line):** Use **Surface A** (httpx against `shopee.co.th/api/v4`) for image/price/sold; **augment with Surface B** for commission via a Playwright-driven *capture* of the signed-in affiliate portal's hidden JSON endpoints (with the user's cookie). If Surface B can't be made to yield a clean JSON, fall back to **Playwright DOM scraping** on the affiliate portal search results page.

> The Playwright cookie helper (`./scripts/refresh_cookie.py`, see other ticket) is a prerequisite for anything in Surface B; Surface A can work for any logged-in browser cookie.

---

## 2. Surface A — `shopee.co.th/api/v4` (public storefront SPA backend)

### 2.1 Discovery and verification

This is the JSON API that the `shopee.co.th` storefront SPA itself calls. It is well known to scrapers. Two independent public references:

- **`akherlan/onlineshop`** (Node.js, ID: https://github.com/akherlan/onlineshop) — uses `https://shopee.co.id/api/v4/*` (Indonesia analogue; the Thai version is `https://shopee.co.th/api/v4/*`). Source: `shopee.js`. Endpoints visible: `/flash_sale/...`, `/pages/get_category_tree`, `/pages/is_short_url`, `/item/get`, `/shop/get_shop_base`, `/recommend/recommend`.
- **StackOverflow "scrape Shopee API v4"** (https://stackoverflow.com/q/73424180) — captures a working call to `https://shopee.co.id/api/v4/search/search_items` and the **header trick** that makes it succeed:
  ```http
  GET /api/v4/search/search_items?by=relevancy&limit=60&match_id=11043145&newest=0&order=desc&page_type=search&rating_filter=4&scenario=PAGE_CATEGORY&version=2 HTTP/1.1
  Host: shopee.co.id
  User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36
  cookie: REC_T_ID=…; SPC_F=…; SPC_EC=…; SPC_U=…; csrftoken=…; …
  referer: https://shopee.co.id/Perawatan-Kecantikan-cat.11043145?page=0&ratingFilter=4
  x-api-source: pc
  af-ac-enc-dat: null
  ```

  The accepted answer adds `af-ac-enc-dat: null` (and `x-api-source: pc`) and the call returns data instead of the `error: 90309999` cookie-mismatch reply. The encoding header is the load-bearing trick.

### 2.2 Endpoints relevant to the four-field destination

All of these are POST-able as GETs. Replace `co.id` with `co.th` for Thailand. Cookie string is harvested from a normal signed-in browser; **the same browser session must produce the cookies** (Shopee binds cookies to fingerprint-derived `SPC_*` values; reusing cookies across machines/fingerprints returns `error: 90309999`).

| Endpoint | Purpose | Notable params | Returns | Useful for |
|----------|---------|---------------|---------|-----------|
| `GET /api/v4/pages/is_short_url` | Cookie bootstrap. Hits the host with no path of consequence; Shopee returns `Set-Cookie` headers needed for subsequent calls. | `path=<any short path>` | cookie set | Establishes a usable cookie string when starting from cold. |
| `GET /api/v4/search/search_items` | Keyword + category-aware search. **This is our primary search endpoint.** | `by=relevancy`\|`ctime`\|`sales`\|`price`; `limit` (≤60); `match_id` (category id, omit for free-text); `newest` (offset, `0`, `60`, `120`, …); `order=desc`\|`asc`; `page_type=search`; `scenario=PAGE_SEARCH`\|`PAGE_CATEGORY`; `version=2`; `keyword=…` | `items[].item_basic` (incl. `itemid`, `shopid`, `name`, `image`, `price`, `price_min`, `price_max`, `historical_sold`, `sold`, `liked_count`, `cmt_count`, `item_rating`, `currency`, `raw_discount`, `shop_name`, `shop_rating`, `is_official_shop`, `is_mart`, `catid`) and `items[].adsid`, `items[].campaignid`, etc. | **`image`, `price`, `sold`** (image from `image` field prefixed with `https://cf.shopee.co.th/file/`; price in micro-units, divide by 100000; sold = `historical_sold`). |
| `GET /api/v4/pdp/get_pc` | Product detail (server-rendered HTML-friendly JSON). | `shop_id=<int>`, `item_id=<int>` | full PDP payload incl. `name`, `description`, `categories`, `price`, `price_min`/`max`, `historical_sold`, `images[]`, `video_info_list`, `item_rating`, `models[]`, `tier_variations[]`, `brand` | cross-check price/sold against search result; richer one-product detail if needed |
| `GET /api/v4/item/get` | Lighter product metadata. | `itemid=<int>`, `shopid=<int>` | cheaper than `get_pc`; enough for an item card | cheap single-item fetch |
| `GET /api/v4/pages/get_category_tree` | Full category tree. | (none) | top-level + children categories | optional category-aware search |
| `GET /api/v4/shop/get_shop_base` | Resolve `username` → `shopid`. | `username=<slug>` | shop base | shop-page walking |
| `GET /api/v4/recommend/recommend` | Category / shop page paginated listings. | `bundle=category_landing_page`\|`shop_page_category_tab_main`; `catid`; `shopid`; `limit` (≤120); `offset`; `tab_name`; `sort_type` | `sections[].data.item` array of item cards | useful when search is replaced by category walk; capacity: 120 items per call |
| `GET /api/v4/flash_sale/get_all_sessions`, `POST /api/v4/flash_sale/flash_sale_batch_get_items` | Flash-sale lists / item batches. | various | flash sale items | not needed unless we want flash deals later |

### 2.3 Required headers for every call

```http
User-Agent: <a desktop Chrome UA string matching the cookie's origin machine; mismatched UA is a soft ban trigger>
Referer: https://shopee.co.th/             # or the actual page URL the cookie was issued from
cookie: <the exact ; -joined cookie string from the same browser session>
x-api-source: pc                          # observed on every documented successful call
af-ac-enc-dat: null                       # the trick. Empty/absent → request returns error 90309999.
content-type: application/json            # only needed for POST; harmless to set on GET
```

Cookie string is the joined `Set-Cookie` values from a real signed-in (or even cold) `shopee.co.th` session. The `is_short_url` bootstrap is a fine way to get one cold, but a logged-in cookie is richer and matches the user's existing browser session.

### 2.4 Field mapping for the destination

Field as the destination names it, * surface A field name(s), * extraction notes:

| Destination field | Surface A source | Notes |
|-------------------|------------------|-------|
| `image` | `items[].item_basic.image` (string, opaque ID) | Prefix with `https://cf.shopee.co.th/file/` → full URL. Some entries include `_tn` suffix; prefer the unsuffixed ID for crisper resolution. |
| `price` | `items[].item_basic.price` (int) **and** `price_min` / `price_max` | Divide by **100000** to get display price in THB. Use `price_min` for promo-range items, `price` for the displayed price. StackOverflow commenters note `price` may show as a randomised value if the call is from a different IP/country — use the search-result price when possible. |
| `sold` | `items[].item_basic.historical_sold` (int) | This is the cumulative-since-listing number. `sold` (recent window) is shorter-term. Pick one; we want "social proof", so `historical_sold`. |
| `commission` | **NOT exposed on Surface A.** | See Surface B below. |

### 2.5 Behaviour caveats observed in the wild

- **Price tamper by IP / locale**: a comment on the SO question notes price numeric values can vary by IP/locale. We're on Thai machine + Thai cookie, so we get Thai display prices. If we ever relocate the script, re-harvest cookies.
- **Stock vs sold mismatch**: `stock` and `historical_sold` are stable across surfaces, but per-tier-variation `stock` is unreliable from `get_pc`. Use `items[].item_basic.stock` when present; ignore model-level stock for v1.
- **Rating inconsistency**: rating_star sometimes doesn't match the on-page stars (off-by-one vote distribution is rounded). Treat rating as a 5-bucket distribution, not a precise float.
- **Cookies are bound to a fingerprint**: the cookie string must be from the same browser where login occurred, or `error: 90309999` comes back and the cookie is effectively dead.

### 2.6 Rate limiting

**Not publicly documented.** Anecdotal from scraper-community writeups: ~1 req/sec sustained is tolerated; bursts of 5–10 in <1 s get throttled (Shopee returns empty arrays or `error_msg: "too frequent"`). The recommended pattern is one search call → render → wait → next. Our usage (search by hand from a UI form) is well under any plausible limit.

If we ever automate (e.g. periodic refresh), enforce:
- minimum 1.0 s between calls,
- exponential backoff on `error_msg`/`error === 90309999`,
- one browser fingerprint per cookie (don't share the cookie across machines / processes).

---

## 3. Surface B — `affiliate.shopee.co.th` (the affiliate portal SPA)

### 3.1 What it is

A SPA at `https://affiliate.shopee.co.th` whose backend is implemented as **JSON over HTTPS** to a small set of `affiliate.shopee.co.th/api/...` or `/graphql` endpoints. After login, the same browser issues authenticated calls from `affiliate.shopee.co.th` (origin-locked). Cookies live under `affiliate.shopee.co.th` and must come from a successful affiliate-portal login.

This is the surface that **exposes commission** to logged-in affiliates, so it is the surface we depend on for that field.

### 3.2 Why this is research, not yet implementation

**The actual endpoint URLs and required headers on `affiliate.shopee.co.th` are not in any public-facing documentation reviewed for this writeup.** They are implementer-side and versioned. To get them concretely, an authenticated session must be opened and DevTools Network tab captured while typing a search term. The Playwright cookie helper will itself produce this data as a side effect of "log in → wait for landing page"; we should pipe those captured calls into a dump file on first run.

### 3.3 What we expect to find (informed inference)

Based on the patterns Shopee uses across all its regional affiliate portals (VN, TH, ID, MY, PH, BR, MX, SG, TW), the search endpoint family is typically:

- `POST /graphql` (or `POST /api/v1/.../search`) — GraphQL query: `query { productOfferV2(keyword: "<q>", limit: 20, sortType: 1) { nodes { itemId commissionRate sellerCommissionRate shopeeCommissionRate commission sales priceMin priceMax productName shopName shopId imageUrl productLink … } } }`
- `GET /api/v?...` for simple cases.

`commissionRate` is a string percent ("0.06" = 6 %); `commission` is the absolute payout per item per sale (`price × commissionRate`). `sales`/`sold` and `priceMin`/`priceMax` mirror the storefront numbers. `imageUrl` is a full URL (not an ID), so no `cf.shopee.co.th/file/` prefix needed.

**Strong caveat:** this is inference from VN OpenAPI documentation (`bcat95/shopee-aff`). It is high-likelihood-correct for TH because all regional affiliate portals share the same engine, but it must be confirmed by capturing traffic from the user's actual session before the search-service ticket is implemented.

### 3.4 Required steps to lift this surface from inference to verified

The cookie helper script in `implement-cookie-refresh-helper.md` should be augmented (or a sibling script added) to:

1. After login, navigate to the affiliate portal's search/product-discovery page.
2. Subscribe to `page.on("request", ...)` and `page.on("response", ...)` for the duration of a real user search.
3. Filter to requests targeting `affiliate.shopee.co.th/graphql` (or whatever appears) and write them to `docs/research/affiliate-observed-traffic.json`.
4. The WriteUp's next iteration cross-references captured URLs and request bodies against the assumed GraphQL shape, and confirms or corrects.

This is one focused empirical task — ~20 minutes of real-browser work plus a `curl` check — and turns the rest of the project from guesswork into a documented contract.

### 3.5 Anti-bot / captcha behaviour

The official docs on `bcat95/shopee-aff` note that "you currently do not have access to the Shopee Affiliate Open API Platform" returns `error: 10035` and rate-limit returns `10030`. The SPA itself has logged-in captcha / Turnstile on some flows (when accessing commissions for high-traffic products). Mitigation: keep request rate low (≤1/s with jittered delays), keep the cookie alive with the helper script, and back off on any 4xx.

---

## 4. Surface C — `open-api.affiliate.shopee.th/graphql` (the official Affiliate OpenAPI)

Listed only so we don't conflate it with Surface B in implementation. Auth is `Authorization: SHA256Credential=<app_id>, Signature=<hmac>, Timestamp=<unix>`. Endpoints documented in `bcat95/shopee-aff`:

- `product_search` (REST) — keyword + limit + offset, returns product data.
- `product_item_get` (REST) — single product by `item_id`.
- `product_offer_v2` / `shop_offer_v2` — GraphQL queries for the offer list with **commission rates**.
- `generateShortLink` (GraphQL mutation) — turn a product URL into an affiliate short link.
- `conversion_report` / `validated_report` — performance / billing.

**Out of scope per the destination** ("without shopee open API"). Mention only for if the user later changes destination: this is the supported path with proper partner credentials and would replace Surface B entirely.

---

## 5. Surface D — `open.shopee.com` (Shopee Open Platform)

Out of scope, period. Listed only to be explicit: do not implement against `open.shopee.com/documents/v2/v2.product.search_item` etc.

---

## 6. Recommended transport

Decision tree:

1. **Default (H1 — httpx against `shopee.co.th/api/v4`)**: covers image, price, sold for any logged-in browser cookie. This is what we implement first.
2. **For commission**:
   - **First try (H1b — httpx against `affiliate.shopee.co.th/api/...` or `/graphql`)**, headers + cookies copied from the same browser session, with the request shape captured per §3.4. Fastest if we can lift it.
   - **Fallback (H2 — Playwright full render)**: open the affiliate-portal search page, type the query, let it render, parse the rendered result cards for commission. Slower, more brittle to layout changes, but guaranteed to work even if the JSON endpoint shifts.

In code, the search-service module should:

- accept a `Transport` protocol with two implementations (`HttpTransport`, `PlaywrightTransport`),
- default to `HttpTransport` for storefront fields,
- accept an environment flag (`SHOPEE_TH_AFFILIATE_TRANSPORT=playwright`) to switch the **affiliate** leg to Playwright when the JSON endpoint isn't reliably callable.

---

## 7. Reproducible verification (what to actually run, in order)

Once a real cookie is in `.env`:

1. **Cold-start cookie bootstrap** (if the user doesn't already have a logged-in cookie):
   ```bash
   curl -sS -c /tmp/spc.txt \
     -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36" \
     "https://shopee.co.th/api/v4/pages/is_short_url?path=anything"
   ```
   Cookie jar is at `/tmp/spc.txt`. Verify `SPC_F`, `SPC_EC`, `csrftoken`, `SPC_T_ID`/`SPC_T_IV` are set.

2. **Search sanity**:
   ```bash
   curl -sS -b /tmp/spc.txt \
     -A "Mozilla/5.0 … Chrome/126.0.0.0 Safari/537.36" \
     -H "x-api-source: pc" \
     -H "af-ac-enc-dat: null" \
     -H "referer: https://shopee.co.th/" \
     "https://shopee.co.th/api/v4/search/search_items?by=relevancy&limit=20&keyword=iphone%2015%20case&newest=0&order=desc&page_type=search&scenario=PAGE_SEARCH&version=2" \
     | jq '.items | length'
   ```
   Expect: `20` (some match); without the `af-ac-enc-dat` header, expect a non-zero `error` code.

3. **Image URL construction**: pick the first `items[].item_basic.image`; prefix `https://cf.shopee.co.th/file/`; `curl -I` it; expect `HTTP/2 200`.

4. **Field extraction spot-check**: pick the first item; read `price`, divide by 100000, and confirm it equals the displayed Thai baht price in the storefront (open the product URL in the same browser).

5. **Affiliate surface empirical capture** (needs a *user* logged in to `affiliate.shopee.co.th`):
   - Run the cookie helper; on landing page, type a search term.
   - Capture `page.on("request")` + `page.on("response")` events filtered to `affiliate.shopee.co.th`.
   - Save the JSON dump as `docs/research/affiliate-observed-traffic.json`.
   - This file is **the** authoritative input for the search-service ticket.

---

## 8. Open items that need empirical input

These sharpen into tickets as the frontier advances:

- The exact `affiliate.shopee.co.th` endpoint URL and GraphQL/REST contract for keyword search. **Resolution path: capture from a real session, dump to `docs/research/affiliate-observed-traffic.json`.** This unblocks the search-service ticket's affiliate leg.
- Whether the affiliate portal returns commission as a single `commissionRate` percentage or a richer `sellerCommissionRate` + `shopeeCommissionRate` + `commission` triple. Affects our Pydantic `Item` model and the schema of the saved-items table.
- Whether the affiliate-portal search offers sold count as `historical_sold` (matches storefront) or as a different field. Affects whether we display two numbers.
- Concrete rate-limit thresholds (the "≤1/s + jitter" guidance is conservative anecdotal). Worth pinning with a one-off script after we have a cookie.
- Login-time captcha presence. The cookie helper will surface this empirically; if a captcha always appears we need to add a manual-entry fallback in the helper.

---

## 9. Sources

- `akherlan/onlineshop` — `shopee.js`. https://github.com/akherlan/onlineshop (last activity 2023; API shape has been stable since). Public mirror of `shopee.co.id/api/v4/*` consumer.
- StackOverflow, "scrape Shopee API v4" (q 73424180, accepted answer by "Hargun IT SOLUTION" Nov 2022): the `af-ac-enc-dat: null` + `x-api-source: pc` discovery.
- StackOverflow, "Shopee API to get products data doesn't seem to work anymore" (q 76936341): same header trick + cookie-bound observation.
- `bcat95/shopee-aff` — README + `Code/`. Comprehensive Affiliate OpenAPI (Surface C) documentation; used here only for Surface B shape inference. https://github.com/bcat95/shopee-aff
- `apify.com/marc_plouhinec/shopee-api-scraper/issues/apiv4searchsearchi…` — notes that brand-page search also uses `/api/v4/search/search_items`. Useful confirmation that the endpoint is the same family.
- `imabyk/affiliate.shopee.co.th` direct DevTools enumeration: not located in public sources for this writeup — flagged as the empirical step.

— end —
