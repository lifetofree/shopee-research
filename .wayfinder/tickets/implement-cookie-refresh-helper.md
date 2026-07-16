---
name: Implement Playwright cookie refresh helper
labels: [wayfinder:task]
status: open
assignee: unassigned
blocked_by: [research-map-data-surfaces]
parent: map
created: 2026-07-16
---

## Question

Build `./scripts/refresh_cookie.py` (invoked as `make refresh-cookie`) that lets a human manually log in once and persists the session for the app to replay.

Concrete plan, anchored in the resolved research (`docs/research/data-surfaces.md`):

- Open a real Chromium via Playwright in **headed** mode.
- Visit `https://shopee.co.th/` first (so `shopee.co.th` cookies are issued), then `https://affiliate.shopee.co.th/` — affiliate-portal cookies are issued under that second origin and may include a portal-specific `SPC_IA` / `affiliate_id` style value.
- Log in interactively to **both** surfaces when prompted (the user can skip `shopee.co.th` if already signed in there). Wait for the post-login signal that the portal search/landing page is reachable.
- Extract cookies from **both** contexts and persist:
  - `SHOPEE_TH_SESSION_COOKIE` — the `; `-joined cookie string for `shopee.co.th` (this is what Surface A reads).
  - `SHOPEE_TH_AFFILIATE_COOKIE` — the `; `-joined cookie string for `affiliate.shopee.co.th` (this is what Surface B reads).
  - `SHOPEE_TH_AFFILIATE_ID` — set to `""` for now (no public confirmation an id-key is required; will be filled by the empirical capture ticket if needed).
- Write to `.env`, overwriting in place (or print to stdout for paste — pick one and document).
- Idempotent on re-run.
- Exit non-zero on timeout/post-login signal failure.

Cookie strings must come from the same Chromium the helper launched — Shopee binds `SPC_*` cookies to a browser fingerprint and reused cookies from another process fail with `error: 90309999`. Do not attempt to harvest cookies via any other browser.

Acceptance: cold-start the helper, log in to both surfaces when prompted, restart `uvicorn`, search via UI — search succeeds with the stored cookie.

Out of scope here: capturing the affiliate portal's hidden API traffic — that's a separate ticket (`capture-affiliate-portal-traffic`) and should be invoked as a follow-up step from this helper (recommended) or independently.
