.PHONY: help venv up local down logs ps deploy-hello migrate migration test test-unit test-modules test-integration test-e2e lint fmt build-module backend-dev backend-run frontend-dev frontend-test frontend-e2e

PY ?= python3
VENV ?= .venv
BIN = $(VENV)/bin
MODEL ?= qwen2.5:14b

help:
	@grep -E '^[a-z0-9-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

venv: ## create .venv with sdk + dev deps
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q -e sdk -r requirements-dev.txt

up: ## start core stack (nats, postgres, tracer, supervisor, memory, gateway, main, web gateway on :8080, the app on :3000)
	docker compose up -d --build

local: ## start Ollama next to the stack and pull MODEL (default qwen2.5:14b) plus bge-m3 for embeddings; then set PLANNER_PROVIDER / EMBED_PROVIDER=ollama
	docker compose --profile local up -d ollama
	docker compose exec ollama ollama pull $(MODEL)
	docker compose exec ollama ollama pull bge-m3

migrate: ## run every owner's Alembic tree to head on the local Postgres (reads .env)
	set -a; . ./.env; set +a; $(BIN)/python scripts/migrate.py

migration: ## OWNER=core|memory NAME=add_x -> autogenerate a revision from the Table metadata against the local Postgres
	set -a; . ./.env; set +a; export DATABASE_URL=$${DATABASE_URL:-postgresql://mycelium:$$POSTGRES_PASSWORD@localhost:$${PG_PORT:-5432}/mycelium}; \
	$(BIN)/alembic -c $(if $(filter core,$(OWNER)),sdk/mycelium_sdk/db/migrations/core,services/memory/migrations)/alembic.ini \
	  $(if $(filter core,$(OWNER)),,-x schema=memory) revision --autogenerate --rev-id $$(date +%Y%m%d%H%M%S) -m "$(NAME)"

down: ## stop core stack and any modules
	-docker ps -q --filter label=mycelium.module | xargs -r docker rm -f
	docker compose down

logs: ## follow core logs
	docker compose logs -f --tail=100

ps: ## list modules via supervisor
	$(BIN)/python scripts/mctl.py list

deploy-hello: ## deploy the example module
	$(BIN)/python scripts/mctl.py deploy hello

build-module: ## NAME=expenses SPEC=specs/expenses.md -> run the builder
	docker compose run --rm builder --name $(NAME) --spec $(SPEC) --publish

backend-dev: ## up the backend only (no frontend) and wait until it answers; services/Makefile has down, logs, restart, dev-web, run
	$(MAKE) -C services dev

backend-run: ## SERVICE=main|memory|gateway|web|supervisor -> one service natively against the compose bus
	$(MAKE) -C services run SERVICE=$(SERVICE)

frontend-dev: ## the app with hot reload on :3000 against the web gateway on :8080 (make up); NEXT_PUBLIC_MOCK=1 for no gateway at all
	cd frontend && pnpm install && pnpm dev

frontend-test: ## typecheck, lint, unit + integration (vitest)
	cd frontend && pnpm install && pnpm typecheck && pnpm lint && pnpm test

frontend-e2e: ## Playwright against a mock-mode production build on :3131 (needs: pnpm exec playwright install chromium)
	cd frontend && pnpm install && pnpm test:e2e

lint: ## ruff
	$(BIN)/ruff check .

fmt:
	$(BIN)/ruff format .

test-unit: ## unit tests (no services needed)
	$(BIN)/pytest -q tests/unit

test-modules: ## each module's own tests, isolated + template smoke check
	$(BIN)/python scripts/test_modules.py

test-integration: ## needs nats + postgres (make up, or CI services)
	$(BIN)/pytest -q -m integration tests/integration

test-e2e: ## needs the full stack running (make up)
	$(BIN)/pytest -q -m e2e tests/e2e

test: test-unit test-modules ## fast tests
