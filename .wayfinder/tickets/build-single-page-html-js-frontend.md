---
name: Build single-page HTML/JS frontend
labels: [wayfinder:task]
status: closed
assignee: Mavis
blocked_by: [implement-fastapi-http-layer]
parent: map
created: 2026-07-16
claimed: 2026-07-16
closed: 2026-07-16
unblocks: [dev-runbook-and-smoke-test]
---

## Resolution (2026-07-16)

**Asset:** `static/{index.html,app.js,styles.css}` + `tests/test_ui.py`. Replaces the placeholder `static/index.html` from the FastAPI ticket. `uv run pytest` → 86/86 green (10 new UI tests + 12 e2e API tests + 30 generation + 17 search + 14 repository + 2 health + 1 placeholder HTML). `uvicorn src.shopee_th.main:app` boots; `/` returns the SPA, `/styles.css` and `/app.js` serve correctly, `/api/saved` still returns `{"items":[]}`.

**Files added (replaced the placeholder `static/index.html`):**

- `static/index.html` — semantic HTML shell. Top bar (brand + tagline); search section (form + status); error banner; results section (grid); saved-items section; three `<template>` blocks for result-card / saved-item / output-row. Single `defer` script tag for `app.js`.
- `static/styles.css` — vanilla CSS with `:root` design tokens (color, radius, shadow). Responsive grid: single column on narrow screens, two columns (results / saved) on wide screens. CSS Grid + Flexbox, no framework. Light-mode focus rings via `:focus-visible`. No `@import` / `@tailwind` / `@apply` (enforced by test).
- `static/app.js` — vanilla JS, IIFE module pattern (no globals leak; `window.ShopeeTH` is the only external exposure, intended for future Playwright smoke). Layered: Constants → State → API → Format → Render → Handlers → Init. ~520 lines.
- `tests/test_ui.py` — 10 static-smoke tests: HTML shell, asset references, required sections, JS IIFE + strict mode, all 7 documented endpoints referenced, idempotency guard, error-banner rendering of `detail.message`/`detail.guidance`, CSS design tokens, no Tailwind, no login UI in the page.

**Architecture / clean-code notes:**

- **IIFE module** — `app.js` is wrapped in `(function () { "use strict"; … })()`. Nothing on `window` except the deliberate `ShopeeTH` test hook.
- **Layered code organization** — constants, state, API helpers, format helpers, render functions, event handlers, init. Single responsibility per function. No function exceeds ~40 lines.
- **DRY via the `request()` wrapper** — every API call goes through one `fetch`-with-timeout helper. Errors are normalized to `Error` with `.message`, `.guidance`, `.code`, `.url` so callers route to the error banner without inspecting responses.
- **Idempotent save UI** — `state.saving` is a `Set<source_id>`. The save button is disabled the moment a click is registered; the in-flight set is cleared in `finally`. The server is already idempotent on `source_id` (per the persistence ticket), so even races are safe.
- **Per-item inflight tracking** — `state.inflight` (a `Set<id>`) gates the caption/clip/remove buttons on a saved item so the user can't double-trigger.
- **No magic strings** — endpoint paths are constructed via the `api` object; HTML strings use `<template>` clones (not `innerHTML`); user-supplied text is escaped before insertion.
- **Defensive error handling** — every `await` is in a `try/catch/finally`. The error banner uses the server's `detail.guidance` (e.g. "run make refresh-cookie") when present. Network errors get a distinct message.
- **Clipboard fallback** — uses `navigator.clipboard.writeText` in secure contexts, falls back to a temporary `<textarea>` + `document.execCommand("copy")` for `http://localhost` over plain HTTP.
- **No magic numbers** — `MAX_LIMIT`, `DEFAULT_LIMIT`, `FETCH_TIMEOUT_MS` are module constants; the 250/300 char caps in the generation output are documented in the spec, not the SPA.
- **No dead code** — every exported symbol (`api`, `formatPrice`, `formatSold`, `state`) is referenced; the `version` field in the smoke hook is used in the test contract.
- **DOM caching** — every `document.getElementById` is hoisted to a `dom` object at init time. Render functions read from the cache.

**Required flows (all wired):**

- ✅ Search bar with Enter / click-submit → `POST /api/search` → grid of result cards (thumbnail, title, price `฿1,290`, sold `1.2K`, commission `6%`, Save button).
- ✅ Re-search replaces results; explicit empty state.
- ✅ Saved items section: per-item thumbnail, title, four fields, Generate caption / Generate clip prompt / Remove buttons, and `<details>`-collapsed output history (captions + clip prompts) loaded async on render.
- ✅ Loading / empty / error states: `searchStatus` (`role="status"` + `aria-live="polite"`), `errorBanner` (`role="alert"`), explicit empty-state for saved items.
- ✅ Errors render via dismissible banner with the server message + guidance (e.g. "Shopee rejected the session cookie (error=90309999) — run `make refresh-cookie` in the same browser you searched in").
- ✅ Idempotent save: `state.saving` Set blocks double-clicks at the UI layer; the server's UNIQUE constraint on `source_id` is the load-bearing guarantee.
- ✅ No login UI in the page (test enforces this).
- ✅ Vanilla JS, no build step, no framework.

**Decisions worth surfacing:**

- **Single `dom` cache populated at init.** All `getElementById` calls run once in `cacheDom()`; the render layer reads from the cache. This avoids re-querying the DOM on every render and makes the data flow obvious.
- **HTML uses `<template>` elements for cloning, not `innerHTML`.** The browser's template tag is a zero-cost way to declare DOM fragments; `cloneNode(true)` gives us a fast, safe way to instantiate them per item. It also keeps the JS template-free (no string concatenation, no `dangerouslySetInnerHTML` analog).
- **Outputs are loaded asynchronously per saved item** after the saved list is rendered. The empty-state "No generations yet." placeholder is shown until the load completes, then replaced with the actual history. New generations are *prepended* (not appended) so the newest is always at the top.
- **Templates live in the HTML, not the JS.** Easier to inspect visually; the JS just clones them. Trade-off: the rendered card structure is split across two files. For a v1 SPA this is fine.
- **CSS uses Grid + Flexbox, not a framework.** Tokenized design (`:root` custom properties) makes a future dark-mode follow-up a small change.
- **`window.ShopeeTH` is the only public surface** for the IIFE. The smoke hook is `version` + `api` + `formatPrice/formatSold` + `state`. A future Playwright test can call these from inside the browser to verify module load.

**Acceptance check (per ticket):**

- ✅ `index.html` self-contained, links `app.js` and `styles.css`.
- ✅ Search bar with Enter / click → renders result grid (thumbnail, name, price, sold, commission, Save).
- ✅ Re-search replaces results; explicit empty state.
- ✅ Saved items section: per-item with Generate caption / clip / Remove + history.
- ✅ On load, fetches existing outputs and displays them under each item.
- ✅ Loading / empty / error states for search and for save.
- ✅ Errors render dismissible banner with server message.
- ✅ Idempotent save (UI guard + server UNIQUE).
- ✅ No login UI in the page; secrets stay in `.env`.
- ✅ Sensible default styling, no UI framework, no theme switcher.
- ✅ Vanilla JS — no React/Vue, no build step, no new dependencies in `pyproject.toml`.
- ✅ Out-of-scope items (a11y deep-dive, mobile-first, i18n) explicitly deferred.

**Out of scope (per ticket, unchanged):** accessibility deep-dive, mobile-first polish, i18n.

## Question

Build the user-facing UI as a single self-contained HTML + CSS + JS page, served by the FastAPI app from the static-files mount. **Vanilla JS — no React/Vue/build step.** A single `index.html` (with linked `app.js` and `styles.css`, or inlined — your call) at the static mount root.

Required flows:

- **Search bar at top.** Typing + Enter (or a search button) calls `POST /api/search` and renders the result grid: thumbnail (`item.image`), product name, price, sold count, commission — per row, with a **"Save"** toggle per row. Re-search replaces results; previous results don't accumulate.
- **Saved items section** (a panel below results, or a simple tab toggle — pick one and document). Shows saved items with, per item:
  - The four fields shown compactly.
  - **"Generate caption"** button → calls `POST /api/saved/{id}/caption`, renders the result in a read-only text area below the item with a **Copy to clipboard** button.
  - **"Generate clip prompt"** button → symmetric.
  - On load, fetch existing outputs (`GET /api/saved/{id}/outputs?kind=...`) and display them under the item so history is preserved across regenerations.
  - **"Remove"** button per saved item → calls `DELETE`.
- **States**: explicit loading / empty / error for search and for save. Errors render a dismissible banner with the server-supplied message; do not swallow them.
- **Idempotency** in the UI: a double-click on "Save" should produce exactly one row (verify visually against the spec — server is already idempotent, this is a UX check that the UI doesn't show "saving…" forever or duplicate the item).
- **Cookies/secret**: the web app itself has no login UI; secrets stay in `.env` on the laptop, never reach the browser.

Sensible default styling — readable on a laptop screen, no UI framework, no theme switcher. Out of scope: accessibility deep-dive (basic labels and keyboard focus only), mobile-first polish (laptop-localhost only), internationalization.

The page must be served and runnable via `make run` against the API built in the prior ticket.
