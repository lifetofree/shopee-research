---
name: Implement Playwright cookie refresh helper
labels: [wayfinder:task]
status: closed
assignee: Claude
blocked_by: [research-map-data-surfaces]
parent: map
created: 2026-07-16
claimed: 2026-07-16
closed: 2026-07-16
unblocks: [capture-affiliate-portal-traffic]
---

## Resolution (2026-07-16)

**Asset:** `scripts/refresh_cookie.py`, wired into `make refresh-cookie` (which also runs `playwright install chromium` first, deferred from the bootstrap ticket). `uv run pytest` → 95/95 green (7 new in `tests/test_refresh_cookie.py`).

**Files created/changed:**

- `scripts/refresh_cookie.py` — opens one headed Chromium context via `playwright.sync_api`, visits `shopee.co.th` then `affiliate.shopee.co.th` in sequence, blocks on an Enter keypress after each (guarded by a 300s `select.select` timeout so a hung/abandoned session exits non-zero rather than hanging forever), extracts `; `-joined cookies per origin via `context.cookies(url)`, and upserts `SHOPEE_TH_SESSION_COOKIE` / `SHOPEE_TH_AFFILIATE_COOKIE` / `SHOPEE_TH_AFFILIATE_ID` into `.env` in place (preserving every other line). `RefreshCookieError` → non-zero exit with a clear stderr message; `KeyboardInterrupt` also exits non-zero.
- `Makefile` — `refresh-cookie` target now runs `uv run playwright install chromium` (idempotent) then the script, replacing the TODO stub.
- `pyproject.toml` — `pythonpath = ["scripts"]` added to `[tool.pytest.ini_options]` (and `scripts` added to ruff's `src`) so the script's pure helpers are importable from tests without a package marker.
- `tests/test_refresh_cookie.py` — 7 unit tests for the two testable-without-a-browser pure functions: `_cookie_header` (joins name=value pairs, empty when no cookies, via a duck-typed fake context) and `_upsert_env_vars` (replaces existing key in place, appends missing key, preserves comments/blank lines, idempotent on rerun, works from empty text).
- `README.md` — added the missing **Troubleshoot** section (cookie expiry / `error: 90309999` / refresh-cookie timeout / blank commission), which the `/review` spec pass had flagged as promised by SPEC.md stories 6 & 33 but absent.
- `.wayfinder/tickets/dev-runbook-and-smoke-test.md` — fixed a stale ticket-id typo in `blocked_by` (`implement-playwright-cookie-refresh-helper` → `implement-cookie-refresh-helper`) so its dependency now actually resolves against this ticket's filename.

**Decisions worth surfacing:**

- **A single Playwright `BrowserContext` for both origins**, not two separate contexts — `context.cookies(url)` already filters correctly per-origin (domain/path/secure matching), so a second context adds nothing but complexity. Cookies from both logins still end up correctly scoped when extracted.
- **The "post-login signal" is a human Enter keypress, not DOM/URL detection** — the affiliate portal's logged-in state (selectors, redirect URL, captcha presence) is explicitly unconfirmed per `docs/research/data-surfaces.md` §3.5/§5, so there's no reliable automated signal to wait on yet. A human-confirmed gate wrapped in a `select.select` timeout satisfies both halves of the ticket's ask ("wait for signal" + "exit non-zero on timeout/signal failure") without inventing a selector that research hasn't verified exists.
- **`.env` is overwritten in place** (the ticket's two options were "overwrite in place" or "print to stdout"). Chose in-place since that's what `config.py`'s `Settings(env_file=".env")` reads directly — no copy-paste step for the user.
- **No `SHOPEE_TH_USER_AGENT` field added** — `services/search.py` already hardcodes a desktop Chrome UA constant for Surface A calls; adding a captured-UA env var would be a second, unrequested change to the config/search wiring outside this ticket's scope. Flagging here in case a cookie-binding mismatch surfaces in practice (research §2.5 notes UA must match the cookie's origin browser) — the fix would be threading the launched Chromium's UA string through `Settings` and `search()`.

**Acceptance check (per ticket):**

- ✅ Headed Chromium via Playwright; visits `shopee.co.th` then `affiliate.shopee.co.th` in that order.
- ✅ Interactive login gate for both surfaces (skippable if already signed in), with a timeout.
- ✅ Extracts and persists `SHOPEE_TH_SESSION_COOKIE`, `SHOPEE_TH_AFFILIATE_COOKIE`, `SHOPEE_TH_AFFILIATE_ID=""`.
- ✅ Writes to `.env` in place; documented in the ticket resolution (this section) and README.
- ✅ Idempotent on re-run (`_upsert_env_vars` unit-tested for this explicitly).
- ✅ Exits non-zero on timeout (`RefreshCookieError`) or `KeyboardInterrupt`.
- ⏳ **Acceptance's live-portal step** ("cold-start the helper, log in, restart uvicorn, search via UI succeeds") **not run** — requires a real Shopee account and interactive login, which this session doesn't have. The script is ready for the user to run `make refresh-cookie` themselves to complete that check.
- ✅ Does not implement `capture-affiliate-portal-traffic` (out of scope, per the ticket) — left as the next open ticket, now unblocked.

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
