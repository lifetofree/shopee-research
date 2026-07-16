---
name: Capture affiliate-portal hidden API traffic
labels: [wayfinder:task]
status: open
assignee: unassigned
blocked_by: [research-map-data-surfaces, implement-cookie-refresh-helper]
parent: map
created: 2026-07-16
---

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
