---
name: Build single-page HTML/JS frontend
labels: [wayfinder:task]
status: open
assignee: unassigned
blocked_by: [implement-fastapi-http-layer]
parent: map
created: 2026-07-16
---

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
