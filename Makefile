.PHONY: help install run test lint e2e smoke dev-reset refresh-cookie capture-affiliate-traffic clean

UV    ?= uv
APP   := src.shopee_th.main:app

help:
	@echo "shopee-th — make targets"
	@echo "  make install                    install deps + create .venv"
	@echo "  make run                        start dev server (reload)"
	@echo "  make test                       unit + e2e API tests (in-process)"
	@echo "  make lint                       ruff check"
	@echo "  make e2e                        live-portal end-to-end (needs SHOPEE_TH_E2E_COOKIE)"
	@echo "  make smoke                      always-on offline smoke"
	@echo "  make dev-reset                  wipe data/shopee_th.db and .env (with prompt)"
	@echo "  make refresh-cookie             headed Chromium → log in → persist cookies to .env"
	@echo "  make capture-affiliate-traffic  empirical Surface B capture"
	@echo "  make clean                      remove caches, .venv, .uv, build artifacts"

install:
	$(UV) sync

run:
	$(UV) run uvicorn $(APP) --reload --host 127.0.0.1 --port 8000

test:
	$(UV) run pytest -m "not e2e"

lint:
	$(UV) run ruff check src tests

e2e:
	@if [ -z "$$SHOPEE_TH_E2E_COOKIE" ]; then \
		echo "set SHOPEE_TH_E2E_COOKIE to run against the live portal; skipping e2e."; \
		exit 0; \
	fi
	$(UV) run pytest -m e2e

smoke:
	$(UV) run pytest tests/test_smoke.py -v

dev-reset:
	@echo "About to delete data/shopee_th.db and .env (if present)."
	@read -p "Continue? [y/N] " r && [ "$$r" = "y" ] || (echo "aborted"; exit 1)
	rm -f data/shopee_th.db .env

refresh-cookie:
	$(UV) run playwright install chromium
	$(UV) run python scripts/refresh_cookie.py

capture-affiliate-traffic:
	$(UV) run playwright install chromium
	$(UV) run python scripts/capture_affiliate_traffic.py

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .uv __pycache__ */__pycache__ */*/__pycache__ *.egg-info build dist
