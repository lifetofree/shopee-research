---
name: Capture affiliate-portal hidden API traffic
labels: [wayfinder:task]
status: closed
assignee: Claude
blocked_by: [research-map-data-surfaces, implement-cookie-refresh-helper]
parent: map
created: 2026-07-16
claimed: 2026-07-16
closed: 2026-07-16
---

## Resolution (2026-07-16) — empirical capture COMPLETE

**Deliverable produced:** `docs/research/affiliate-observed-traffic.json` — a scrubbed, truncated dump of a real logged-in Shopee Affiliate TH session, captured via a manual DevTools HAR export from the user's genuine Chrome. Surface B is now a **confirmed** contract, no longer inference.

**Confirmed findings (full detail in `docs/research/data-surfaces.md` §3.2):**

- The product-offer endpoint is **`GET /api/v3/offer/product/list`** (REST), **not** the inferred GraphQL `productOfferV2`. Params: `list_type`, `sort_type`, `page_offset`, `page_limit`, `client_type`.
- **One call returns all four destination fields** (image, price, sold, commission) — Surface B alone can serve the destination.
- **Commission** is `seller_commission_rate` / `default_commission_rate` / `max_commission_rate` (string percents like `"7%"`), **not** the single `commissionRate` or the inferred triple. Use `seller_commission_rate` → `default_commission_rate`.
- Product data nests under each list item's `batch_item_for_item_card_full` (mirrors Surface A `item_basic`).
- `POST /api/v3/gql` exists but carries only tabs/campaigns (`getOfferTabList`, `isAffiliateHasNoImpressionCampaign`) — **not** products. The inferred `productOfferV2` was never observed.

**How the capture was actually obtained (important for future captures):**

- **All automated-browser paths were detected by Shopee's anti-bot:**
  - Playwright's bundled Chromium (even with stealth flags) → hard `scene=crawler_item` captcha redirect.
  - Real Chrome via `--remote-debugging-port` (CDP attach) → softer "Loading Issue" error wall.
- **Only a plain, manually-opened real Chrome worked.** The deliverable came from the user exporting a HAR file via DevTools in their everyday Chrome. `scripts/capture_affiliate_traffic.py` was extended (stop-file signal instead of stdin-EOF, gzip body decompression, resilient `goto`, system-Chrome-attach mode) but its automated path is now understood to be unviable for *this* portal; the manual HAR route is the documented method. Future captures should reuse that route.

**Open sub-question (flagged, not blocking):** the captured session listed products by tab (`list_type=0`); a `keyword` param was **not** observed. Before the search-service Surface B re-implementation finalises, confirm whether `/api/v3/offer/product/list` accepts a `keyword`, or whether keyword search is a separate endpoint (one more manual capture with a keyword typed answers this). See `data-surfaces.md` §3.4.

**Next:** re-implement Surface B in `services/search.py` (`_fetch_surface_b` + `AFFILIATE_GRAPHQL_QUERY`) against this REST contract, replacing the inferred GraphQL scaffolding.

---

## Progress (2026-07-16) — tooling built, empirical capture still pending

**Status stays `open`**, deliberately not `closed`: the ticket's actual deliverable is the *data file* (`docs/research/affiliate-observed-traffic.json`), not the script — and that file doesn't exist yet. Producing it requires a real, logged-in Shopee Affiliate TH session driven by a human (login, possibly a captcha, then a manual search inside the portal), which this session has no way to do — no account, no ability to interactively complete a live login. So the tool is ready; the actual capture is not done, and Surface B in `services/search.py` is still unconfirmed best-effort scaffolding.

**Asset:** `scripts/capture_affiliate_traffic.py`, wired into `make capture-affiliate-traffic` (also runs `playwright install chromium` first, same as `refresh-cookie`). `uv run pytest` → 104/104 green (9 new in `tests/test_capture_affiliate_traffic.py`).

**Files created/changed:**

- `scripts/capture_affiliate_traffic.py` — opens one headed Chromium context to `affiliate.shopee.co.th`, attaches `page.on("request"/"response")` listeners filtered to that host (`_is_target_host`, matches exact host + subdomains), and waits up to 60s (or an Enter keypress, whichever comes first — a normal stop condition here, not a failure like the login gate in `refresh_cookie.py`) while the **user** logs in and drives a real search inside the browser themselves. The portal's search UI (selectors, URL, DOM) is explicitly unconfirmed per `docs/research/data-surfaces.md` §3.2/§3.3, so there's nothing for the script to click through on the user's behalf — it only listens and records. Each matched request/response pair is written as `{method, url, headers, post_data, status, response_headers, response_body_truncated, truncated}` to `docs/research/affiliate-observed-traffic.json` (plain overwrite on rerun — trivially idempotent). Response bodies are truncated to 4096 UTF-8 bytes (`_truncate_body`, byte-safe against multi-byte cutoffs). `main()` exits non-zero with a hint if fewer than 3 requests were captured, matching the ticket's "≥3 distinct request types" acceptance bar.
- `Makefile` — `capture-affiliate-traffic` target now runs `playwright install chromium` then the script, replacing the TODO stub.
- `tests/test_capture_affiliate_traffic.py` — 9 unit tests for the three pure, Playwright-free helpers: `_is_target_host` (exact host, subdomain, rejects other hosts including a decoy domain-as-path trick), `_truncate_body` (under-limit passthrough, over-limit truncation, UTF-8 byte-safety with multi-byte characters), `_make_entry` (shape matches the ticket's documented fields, truncation flag, missing/non-text response body).

**Decisions worth surfacing:**

- **The script does not attempt the search itself** — unlike a scenario where selectors are known, the affiliate portal's DOM is explicitly unconfirmed (research marks Surface B as open/inference-only). Automating clicks against unknown selectors would be guesswork layered on guesswork; the ticket's own acceptance bar just needs *a* real recorded session, so a human driving the browser while the script listens is the correct scope for this iteration.
- **No cookie-jar reuse from `refresh_cookie.py`** — the ticket suggests reusing the same browser/cookie jar "would be ideal," but injecting persisted cookies into a fresh Chromium launch risks the exact fingerprint mismatch (`error: 90309999`) the research write-up warns against. A fresh interactive login, same as `refresh_cookie.py`'s own pattern, avoids that risk entirely at the cost of one extra login.
- **Exit code reflects the request-count acceptance bar** (`< 3` → exit 1) so `make capture-affiliate-traffic` fails loudly if the capture window closed before enough traffic was seen, rather than silently producing a useless near-empty dump.

**What's left for this ticket to actually close:**

1. Run `make capture-affiliate-traffic` with a real, logged-in Shopee Affiliate TH account.
2. Log in when the browser opens, navigate to the portal's search/offers page, run a real search term.
3. Confirm `docs/research/affiliate-observed-traffic.json` has ≥3 distinct request types and at least one matches the inferred `productOfferV2`/`product_search` GraphQL shape.
4. Once confirmed, a follow-up pass updates `services/search.py`'s Surface B implementation (`_fetch_surface_b` / `AFFILIATE_GRAPHQL_QUERY`) against the *real* contract instead of the inferred one, and this ticket can move to `closed`.

## Question

Run a one-shot empirical capture that lifts Surface B from inference to a documented contract. The research write-up notes that the `affiliate.shopee.co.th` JSON endpoints are not in any public docs reviewed; we need a recorded session.

Build (or extend) a script — e.g. `./scripts/capture_affiliate_traffic.py`, exposed as `make capture-affiliate-traffic` — that:

- Opens a headed Chromium via Playwright to `https://affiliate.shopee.co.th/`.
- Waits for the user to log in interactively (resuing the same browser the cookie helper used would be ideal — same fingerprint, same cookie jar).
- Navigates to the portal's "search products" or "browse offers" page.
- Types a real, harmless search term (e.g. `iphone 15 case`).
- While the page reacts, attaches `page.on("request", ...)` and `page.on("response", ...)` listeners filtered to `affiliate.shopee.co.th` (and the resulting `Set-Cookie` headers).
- Writes a structured dump to `docs/research/affiliate-observed-traffic.json` — each entry: `{method, url, headers, post_data, status, response_headers, response_body_truncated}` (truncate bodies to ~4 KB to keep the dump readable; flag truncation in the entry).
- Stops after the user presses Enter in the terminal (or after a fixed window of 60 s of typing).
- Idempotent: re-run overwrites the dump file.

Acceptance: `docs/research/affiliate-observed-traffic.json` exists, contains ≥3 distinct request types for the affiliate portal, and at least one of them matches the inferred GraphQL shape (`productOfferV2` or `product_search`-style query). Once accepted, the empirical JSON becomes input to the next iteration of the search-service ticket — its "Secondary surface (Surface B)" block can be filled with concrete URLs, request bodies, and response shapes.

This is the bridge between the research write-up and the search-service implementation; before this lands, the affiliate leg in search-service is best-effort scaffolding only.
