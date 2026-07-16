---
name: Dev runbook + end-to-end smoke test
labels: [wayfinder:task]
status: open
assignee: unassigned
blocked_by: [build-single-page-html-js-frontend, implement-cookie-refresh-helper]
parent: map
created: 2026-07-16
---

## Question

Wrap the project into a runnable developer experience and prove the path end-to-end against the real affiliate portal (with the user's cookie).

- **README** (replace the bootstrap-ticket stub with real prose; keep it short): sections for **Prereqs** (Python ≥ 3.11, `uv`, ~200MB disk for Playwright Chromium), **First-time setup** (`uv sync`, `make refresh-cookie` to populate `.env`), **Run** (`make run`, open `http://localhost:8000`), **Use** (one-line: type a product name, save items, generate), and **Troubleshoot** (esp. cookie-expired symptoms — what the UI shows, what the logs show, the `make refresh-cookie` remedy).
- **`make e2e`** target: boot `uvicorn` in the background, hit every API endpoint via `httpx` end-to-end (search → save idempotency check → list → caption generation → outputs → clip-prompt generation → outputs → delete → list-empty). Uses a real cookie if `SHOPEE_TH_E2E_COOKIE` is in env; otherwise skip with an explanatory `pytest.skip` and a clear console message ("set SHOPEE_TH_E2E_COOKIE to run against live portal"). Test passes iff every endpoint returns the documented shape and assertions hold.
- **`make dev-reset`**: wipe `data/shopee_th.db` and `.env` (with confirmation prompt — never silently).
- **`make smoke`**: spin the app up against mock services (no network) and assert the page renders + the API responds OK. Always-on; no env var required.

Self-verification: after this ticket, you can, on a clean machine:

1. `git clone` (or `cp -r`) the project,
2. follow README prereqs,
3. run `make refresh-cookie` once,
4. run `make run`,
5. complete a full search → save → caption → clip-prompt → delete loop in the UI,
6. run `make e2e` (with a cookie) and have it pass.
