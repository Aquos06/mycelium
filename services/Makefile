# mycelium backend. `make dev` brings it up: nats, postgres and every service in this folder, in docker, and
# waits until they answer. The frontend has its own loop (`make frontend-dev` at the root, or `cd frontend`).
#
#   make dev                    # up the backend (build what changed, wait until healthy, print the URLs)
#   make down                   # stop it (volumes kept)
#   make logs SERVICE=main      # follow one service, or all
#   make restart SERVICE=web    # rebuild + restart one service
#   make dev-web                # a hot loop: the web gateway natively on :8081 with reload, on the same bus
#   make run SERVICE=main       # one service natively, as its container runs it
#   make test-unit              # the fast gate; test-integration and test-e2e run against the stack `make dev` started
#
# Native targets read the repo's .env; NATS_URL and DATABASE_URL fall back to the published host ports when
# the .env names no host-side ones (the containers' nats:4222 / postgres:5432 are not reachable from the host).

ROOT := $(abspath ..)
VENV ?= $(ROOT)/.venv
BIN := $(VENV)/bin
PY ?= python3
COMPOSE ?= docker compose --project-directory $(ROOT)
BACKEND := nats postgres tracer supervisor memory gateway main web
# the native gateway's port: 8080 is the compose one
PORT ?= 8081
SERVICE ?=
RELOAD_DIRS := --reload-dir $(ROOT)/services/web --reload-dir $(ROOT)/sdk/mycelium_sdk
ENV = set -a; . $(ROOT)/.env; set +a; export NATS_URL=$${NATS_URL:-nats://localhost:$${NATS_PORT:-4222}}; export DATABASE_URL=$${DATABASE_URL:-postgresql://mycelium:$$POSTGRES_PASSWORD@localhost:$${PG_PORT:-5432}/mycelium}; export PYTHONPATH=$(ROOT)/services:$(ROOT)/services/supervisor

.DEFAULT_GOAL := help
.PHONY: help dev up down restart build logs ps urls dev-web run install test test-unit test-integration test-e2e lint fmt migrate migration shell env clean

help: ## this list
	@grep -E '^[a-z0-9-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------------------------------- the stack

dev: ## up the backend: nats, postgres, tracer, supervisor, memory, gateway, main, web gateway; waits until healthy
	$(COMPOSE) up -d --build --wait --wait-timeout 300 $(BACKEND)
	@$(MAKE) --no-print-directory urls

up: dev ## the same as dev

down: ## stop the backend and any modules the supervisor started (volumes kept)
	-docker ps -q --filter label=mycelium.module | xargs -r docker rm -f
	$(COMPOSE) stop $(BACKEND)

restart: ## SERVICE=web -> rebuild one service's image and restart it (no SERVICE: all of them)
	$(COMPOSE) up -d --build --wait $(or $(SERVICE),$(BACKEND))

build: ## build every backend image without starting anything
	$(COMPOSE) build $(BACKEND)

logs: ## SERVICE=main -> follow one service's logs (no SERVICE: all of them)
	$(COMPOSE) logs -f --tail=100 $(or $(SERVICE),$(BACKEND))

ps: ## what is running, and the modules the supervisor knows
	$(COMPOSE) ps $(BACKEND)
	@$(ENV); $(BIN)/python $(ROOT)/scripts/mctl.py list 2>/dev/null || echo "(the supervisor is not answering yet: it builds module-base on a fresh start)"

urls: ## where the backend answers on this host
	@$(ENV); echo "web gateway   http://localhost:$${WEB_PORT:-8080}/api/v1/system/health   (the app: http://localhost:$${FRONTEND_PORT:-3000}, make frontend-dev, or docker compose up -d frontend)"; \
	echo "nats          $$NATS_URL   monitor http://localhost:$${NATS_MON_PORT:-8222}"; \
	echo "postgres      $$DATABASE_URL" | sed -E 's#:[^:@/]+@#:…@#'; \
	curl -sf "http://localhost:$${WEB_PORT:-8080}/api/v1/system/health" >/dev/null && echo "web gateway answers" || echo "web gateway not answering yet"

# ---------------------------------------------------------------------------------------------- native, for a loop

dev-web: ## the web gateway natively on :8081 (PORT=) with hot reload, on the bus `make dev` started
	@echo "web gateway  http://localhost:$(PORT)/api/v1/system/health"
	@echo "the app      cd ../frontend && NEXT_PUBLIC_API_BASE=http://localhost:$(PORT) pnpm dev"
	$(ENV); $(BIN)/uvicorn --factory web.__main__:app --host 127.0.0.1 --port $(PORT) --reload $(RELOAD_DIRS) --no-access-log

run: ## SERVICE=main|memory|gateway|web|supervisor -> one service natively, as its container runs it (stop the container first)
	@test -n "$(SERVICE)" || (echo "usage: make run SERVICE=main|memory|gateway|web|supervisor"; exit 1)
	$(ENV); cd $(ROOT)/services && $(BIN)/python -m $(if $(filter supervisor,$(SERVICE)),supervisor.app,$(SERVICE))

install: ## .venv with the sdk (editable), the dev tools and every service's requirements.txt
	test -x $(BIN)/python || $(PY) -m venv $(VENV)
	$(BIN)/pip install -q -e $(ROOT)/sdk -r $(ROOT)/requirements-dev.txt $(foreach r,$(wildcard */requirements.txt),-r $(r))

shell: ## a python with the env loaded and every service importable
	$(ENV); cd $(ROOT)/services && $(BIN)/python

env: ## the host-side URLs the native targets run with (password hidden)
	@$(ENV); echo "NATS_URL=$$NATS_URL"; echo "DATABASE_URL=$$DATABASE_URL" | sed -E 's#:[^:@/]+@#:…@#'

# ------------------------------------------------------------------------------------------------------- checks

test-unit: ## the fast gate: no nats, no postgres
	cd $(ROOT) && $(BIN)/pytest -q tests/unit

test-integration: ## against the nats + postgres `make dev` started
	$(ENV); cd $(ROOT) && $(BIN)/pytest -q -m integration tests/integration

test-e2e: ## against the whole stack `make dev` started
	$(ENV); cd $(ROOT) && $(BIN)/pytest -q -m e2e tests/e2e

test: test-unit test-integration ## unit + integration

lint: ## ruff check
	cd $(ROOT) && $(BIN)/ruff check sdk services scripts tests

fmt: ## ruff format
	cd $(ROOT) && $(BIN)/ruff format sdk services scripts tests

migrate: ## every owner's Alembic tree to head on the local postgres
	$(MAKE) -C $(ROOT) migrate

migration: ## OWNER=core|memory NAME=add_x -> autogenerate a revision (never hand-write one)
	$(MAKE) -C $(ROOT) migration OWNER=$(OWNER) NAME=$(NAME)

clean: ## caches
	find $(ROOT)/services $(ROOT)/sdk -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf $(ROOT)/.pytest_cache $(ROOT)/.ruff_cache
