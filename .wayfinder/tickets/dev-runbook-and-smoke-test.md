---
name: Dev runbook + end-to-end smoke test
labels: [wayfinder:task]
status: closed
assignee: Claude
blocked_by: [build-single-page-html-js-frontend, implement-cookie-refresh-helper]
parent: map
created: 2026-07-16
claimed: 2026-07-16
closed: 2026-07-16
---

## Resolution (2026-07-16)

**Asset:** README's Troubleshoot section (added in the prior cookie-refresh-helper ticket) plus `Prereqs`/`First-time setup`/`Run`/`Use`/`Make targets`/`Layout` were already in place; `make e2e` and `make smoke` now run real tests instead of stubs. `uv run pytest` → 107 passed, 1 skipped (the live e2e test self-skips without a cookie).

**Files created/changed:**

- `tests/test_smoke.py` — 3 always-on tests booting the app against mocks (shared `app`/`client` fixtures, moved to `conftest.py`): frontend page renders (`GET /` returns HTML), `/health` responds OK, and `POST /api/search` responds OK. No env var, no network.
- `tests/test_e2e.py` — the live counterpart. `@pytest.mark.e2e`. A `live_client` fixture skips via `pytest.skip(...)` when `SHOPEE_TH_E2E_COOKIE` is unset; when set, it spawns a **real `uvicorn` subprocess** (not the in-process ASGI transport `test_api.py` uses) on a free port, waits for `/health` to respond, and yields an `httpx.AsyncClient` against it. The one test drives the full documented lifecycle: search → save → re-save (idempotency check on the returned `id`) → list → generate caption → list caption outputs → generate clip-prompt → list clip-prompt outputs → delete → list-empty — matching the ticket's exact sequence.
- `tests/conftest.py` — the `app`/`client` fixtures moved here from `test_api.py` (verbatim) so `test_smoke.py` can reuse them without duplicating ~40 lines of boot plumbing; `test_api.py` now just imports what it still needs (`Settings`, `create_app`, `NoopTransport`, `TransportResponse`) for its own tests and the two module-level canned-data helpers (`_surface_a_ok`, `_item`).
- `pyproject.toml` — registered the `e2e` marker (avoids the "unknown marker" warning) and added it to a fresh `[tool.pytest.ini_options].markers` list.
- `Makefile` — `smoke` now runs `pytest tests/test_smoke.py -v` (was a one-line `python -c` import check); `test` now runs `pytest -m "not e2e"` (was unfiltered plain `pytest` — hardens against a stray `SHOPEE_TH_E2E_COOKIE` in someone's shell silently making the offline test target hit the live network); removed the now-unused `PYTHON` Makefile variable.
- **`src/shopee_th/models/db.py`** — real bug found and fixed while dry-running the `test_e2e.py` subprocess-boot mechanism (with a dummy cookie, hitting only `/health`, no live Shopee traffic): a fresh clone has no `data/` directory, and aiosqlite doesn't create the parent directory for `sqlite+aiosqlite:///./data/shopee_th.db` itself, so `create_engine()` crashed on the very first connection attempt — meaning `make run` would have crashed on startup on literally any clean clone, failing the ticket's own self-verification checklist at step 4. Added `_ensure_sqlite_dir()`, called from `create_engine()`, which `mkdir(parents=True, exist_ok=True)`s the parent directory for any file-based SQLite URL (no-op for `:memory:` or non-SQLite URLs). Verified the fix by deleting `data/` and `.env`, booting `uvicorn` directly (not via subprocess helper), and confirming `GET /` → 200, `GET /health` → 200, `POST /api/search` → 502 (expected: no real cookie configured yet — exactly what a first-time user sees before `make refresh-cookie`).
- README — `make test`'s row in the Make targets table updated to reflect the `-m "not e2e"` filter.

**Decisions worth surfacing:**

- **`test_e2e.py` boots a real `uvicorn` subprocess**, not the ASGI in-process transport `test_api.py` uses — the ticket explicitly asks to "boot uvicorn in the background," which is a materially different (and more faithful) check than the mocked in-process suite: it exercises the actual deployable process, real port binding, and (when a cookie is set) the real `HttpTransport` against the real Shopee network, not `NoopTransport`.
- **The live lifecycle test itself was not run against the real portal** — this session has no real Shopee Affiliate TH account/cookie. What *was* verified: (a) the skip path (`pytest.skip` fires correctly without `SHOPEE_TH_E2E_COOKIE`), and (b) the subprocess-boot/teardown mechanism itself, using a dummy cookie and touching only the local `/health` endpoint — deliberately avoiding any live request to Shopee's production servers with a fake credential. The full search→save→...→delete assertions against the live portal are unverified until a real cookie is available; per the ticket's own acceptance step 6, that's a live run the user needs to do (`make e2e` with `SHOPEE_TH_E2E_COOKIE` set from a real `make refresh-cookie` session).
- **`make test` now excludes `e2e`-marked tests via `-m "not e2e"`** — not explicitly asked for, but a one-line hardening directly motivated by adding a marker that *can* hit a live third-party network: without the exclusion, a developer with `SHOPEE_TH_E2E_COOKIE` already exported for unrelated reasons would have the "fast, offline" test target silently make live calls.
- **The `data/` directory bug was in scope to fix here**, not filed as a separate follow-up — it directly blocks this ticket's own self-verification checklist (`make run` on a clean machine) and was discovered as a direct side effect of building the tooling this ticket asked for.

**Acceptance check (per ticket):**

- ✅ README has Prereqs / First-time setup / Run / Use / Troubleshoot (cookie-expired symptoms + remedy) — Troubleshoot landed in the prior ticket, still accurate and referenced here.
- ✅ `make e2e`: boots real `uvicorn`, hits every documented endpoint via `httpx`, end-to-end, in the documented sequence; skips via `pytest.skip` with a clear message when `SHOPEE_TH_E2E_COOKIE` is unset.
- ✅ `make dev-reset`: unchanged, already wiped `data/shopee_th.db` + the env file with a confirmation prompt (bootstrap ticket).
- ✅ `make smoke`: boots the app against mocks, asserts page renders + API responds OK, always-on, no env var.
- ⏳ **Self-verification steps 3, 5, 6** (real `make refresh-cookie` login, a real search→save→generate loop in the UI, `make e2e` passing with a real cookie) **not run** — needs the user's real account, same limitation as the two prior tickets.
- ✅ Steps 1, 2, 4 self-verified this session: clean-state boot (`data/` and env file removed, `make run` equivalent booted directly) served `/` and `/health` successfully, confirming the app comes up on a fresh clone.

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
