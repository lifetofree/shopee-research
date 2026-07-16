---
name: Research — Map the available Shopee Affiliate TH data surfaces
labels: [wayfinder:research]
status: closed
assignee: droid
blocked_by: []
parent: map
created: 2026-07-16
claimed: 2026-07-16
closed: 2026-07-16
unblocks: [implement-cookie-refresh-helper, implement-search-service, capture-affiliate-portal-traffic]
---

## Resolution (2026-07-16)

**Asset:** `docs/research/data-surfaces.md` (linked from this ticket). Three live surfaces catalogued for the project.

**Key findings:**

- **Surface A** (`shopee.co.th/api/v4` — public storefront SPA backend) is reachable from a normal `shopee.co.th` logged-in browser cookie and exposes **image / price / sold** for keyword search via `GET /api/v4/search/search_items`. Critical headers are `x-api-source: pc` and `af-ac-enc-dat: null` (without the latter, every call returns `error: 90309999` regardless of cookie quality). Price is micro-units; divide by `100000` for THB. Image is an opaque ID; prefix `https://cf.shopee.co.th/file/`. Source corroborated by `akherlan/onlineshop` (Node.js reference implementation against `co.id`) and StackOverflow q/73424180 (the `af-ac-enc-dat` discovery).
- **Surface B** (`affiliate.shopee.co.th` SPA backend) is the home of **commission**. Endpoints are undocumented; shape inferred from the cross-region Affiliate OpenAPI docs (`bcat95/shopee-aff` GraphQL/REST families — `productOfferV2`, etc.). Empirical capture from a real signed-in session is required to confirm; that capture becomes a new ticket (`capture-affiliate-portal-traffic`).
- **Surfaces C & D** (Affiliate OpenAPI on `open-api.affiliate.shopee.th/graphql`, and `open.shopee.com` / Open Platform) are **out of scope** per the destination ("without shopee open API"). Catalogued only so we don't conflate them with B during implementation.
- **Cookies are bound to a browser fingerprint.** Sharing cookies across machines / fingerprints returns `error: 90309999`. This is the load-bearing reason our cookie helper refreshes from the same browser we'll search with.
- **Recommended transport:** H1 (httpx) for Surface A; H2 (Playwright) as fallback for Surface B's commission row if the JSON endpoint can't be captured cleanly.

**Downstream deltas:**

- `implement-cookie-refresh-helper` and `implement-search-service` tickets updated with concrete endpoints, headers, image-prefix rule, and price divisor.
- New ticket **`capture-affiliate-portal-traffic`** created (HITL, depends on this ticket) — Playwright-driven one-shot that logs in to `affiliate.shopee.co.th`, types a real search term, and dumps all network calls to `docs/research/affiliate-observed-traffic.json`. This is the empirical input that turns Surface B from inference to contract.

**Graduated from "Not yet specified":**

- "Exact field names, types, and JSON nesting" — partially answered for Surface A (endpoint URLs + headers + image/price/sold now concrete). Full contract for Surface B still depends on the empirical capture ticket.
- "Whether `affiliate_id` / `shop_id` is required alongside the cookie to render commission, and whether captcha/anti-bot measures appear at login" — partially answered: no `affiliate_id` known to be required (Shopee binds identity into `SPC_*` cookies themselves); captcha presence is empirical and surfaced by `implement-cookie-refresh-helper`.
- "Whether the public `shopee.co.th` storefront search is a viable parallel/complementary surface when commission isn't exposed" — confirmed: yes; storefront is **necessary** for image/price/sold since Surface B commissions are minimal-context items.
- "Concrete rate-limit / cooldown policy observed against the chosen surface" — anecdotal answer surfaced (≤1 req/s sustained is tolerated; bursts trigger throttling), but precise numbers remain empirical.

---

## Question

What surfaces does Shopee Affiliate Thailand expose that we can hit for product search + the four fields (image, commission, price, sold) without invoking the Shopee Open API? Enumerate the candidates, document auth requirements for each, observe behaviors empirically, and recommend one transport with a fallback.

Specifically, surface and document:

- **`affiliate.shopee.co.th`** — request shapes (search endpoints, JSON payloads), cookie/header requirements (which specific cookies, `Referer`/`Origin`/`X-Api-Source` or similar headers commonly required by Shopee's portals), the response JSON for a typical product listing (every field available, not just the four), and how commission is exposed per item.
- **`shopee.co.th` public storefront search** — same, as a parallel surface; useful as a fallback when commission isn't exposed by the affiliate surface, and to cross-check price/sold.
- **Any mobile-API endpoint** the affiliate portal's SPA itself calls (visible via DevTools Network tab on a real, signed-in search; capture the exact URL pattern, query params, headers, and request body).
- **Rate limits, error shapes, captcha/anti-bot behaviors observed** when calling repeatedly.
- **Transport choice** (hidden JSON API via httpx is preferred; Playwright browser as fallback; plain HTML parse last resort) with a one-line justification anchored in what you observed.

The write-up must be specific and reproducible: cookie names, header values, and example payloads — not "look in DevTools." Where a value is partner-specific or signs dynamically, say so explicitly.

**Output**: a markdown write-up at `docs/research/data-surfaces.md` linked from this ticket's resolution comment.
