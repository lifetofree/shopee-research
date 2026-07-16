# shopee-th

Local FastAPI web app for Shopee Affiliate Thailand — search products by name, save to a local SQLite store, and generate Thai caption + English clip-prompt via templated stubs (LLM-ready interface).

> Spec: [`docs/SPEC.md`](docs/SPEC.md). Project plan: [`.wayfinder/map.md`](.wayfinder/map.md) and [`.wayfinder/tickets/`](.wayfinder/tickets/).

## Prereqs

- Python ≥ 3.11
- [`uv`](https://github.com/astral-sh/uv) (package manager)
- ~200 MB disk for Playwright Chromium

## First-time setup

```bash
uv sync                          # install deps + create .venv
make refresh-cookie              # one-time interactive: log in to Shopee, persist cookies to .env
```

## Run

```bash
make run                         # uvicorn src.shopee_th.main:app --reload on http://localhost:8000
```

## Use

Open <http://localhost:8000>, type a product name, save items, click **Generate caption** or **Generate clip prompt**.

## Make targets

| Target | Purpose |
|--------|---------|
| `make run` | Start the dev server (reload on change). |
| `make test` | Run the unit + e2e API test suite. |
| `make lint` | Run ruff. |
| `make e2e` | Boot uvicorn, hit every API endpoint end-to-end. Requires `SHOPEE_TH_E2E_COOKIE`; otherwise skipped. |
| `make smoke` | Spin the app up against mocks; always-on. |
| `make dev-reset` | Wipe `data/shopee_th.db` and `.env` (with confirmation). |
| `make refresh-cookie` | Headed Chromium → log in to Shopee → persist cookies to `.env`. |
| `make capture-affiliate-traffic` | Empirical Surface B capture to `docs/research/affiliate-observed-traffic.json`. |

## Troubleshoot

- **Search fails / cookie expired**: re-run `make refresh-cookie` and log in again — Shopee session cookies expire and are also bound to the browser fingerprint that produced them, so cookies copied from anywhere other than that helper run will fail.
- **`error: 90309999` from Shopee**: the cookie doesn't match the browser fingerprint it was issued to (e.g. copied from another machine/browser). Re-run `make refresh-cookie`; don't hand-copy cookies from a different session.
- **`make refresh-cookie` times out**: the login step has a 5-minute window per site. Re-run the command and complete the login (or captcha, if one appears) before it lapses.
- **Commission always shows blank**: expected until `capture-affiliate-portal-traffic` lands a confirmed Surface B contract — the affiliate leg is best-effort in the meantime.

## Layout

See [`docs/SPEC.md`](docs/SPEC.md) for the full structure; the package is `src/shopee_th/{api,services,models,templates}/` with `scripts/`, `tests/`, and `docs/` at the project root.

## License

Personal project. Not licensed for redistribution.
