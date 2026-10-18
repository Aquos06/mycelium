.PHONY: help venv up down logs ps deploy-hello test test-unit test-modules test-integration test-e2e lint fmt build-module

PY ?= python3
VENV ?= .venv
BIN = $(VENV)/bin

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

venv: ## create .venv with sdk + dev deps
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q -e sdk -r requirements-dev.txt

up: ## start core stack (nats, postgres, tracer, supervisor)
	docker compose up -d --build

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
