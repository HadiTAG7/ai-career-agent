.DEFAULT_GOAL := help

.PHONY: help config up dev down restart ps logs api-logs web-logs \
	api-install api-lint api-test api-migrate api-migration-check web-install web-lint \
	web-typecheck web-test web-build check

help: ## Show available commands
	@echo "AI Career Agent commands"
	@echo "  make config       Validate the Compose configuration"
	@echo "  make up           Build and start the local stack"
	@echo "  make dev          Run the local stack in the foreground"
	@echo "  make down         Stop containers (keeps database volumes)"
	@echo "  make ps           Show container and health status"
	@echo "  make logs         Follow all service logs"
	@echo "  make api-test     Run backend tests with the local Python environment"
	@echo "  make web-build    Build the Next.js application"
	@echo "  make check        Run API lint/tests and web lint/build"

config: ## Validate docker-compose.yml after creating .env
	docker compose config --quiet

up: ## Build and start all services
	docker compose up --build --detach --wait

dev: ## Build and run all services in the foreground
	docker compose up --build

down: ## Stop containers without deleting data volumes
	docker compose down

restart: ## Restart the running stack
	docker compose restart

ps: ## Show service health
	docker compose ps

logs: ## Follow logs from every service
	docker compose logs --follow --tail=200

api-logs:
	docker compose logs --follow --tail=200 api

web-logs:
	docker compose logs --follow --tail=200 web

api-install: ## Install API and development dependencies in the active Python environment
	python -m pip install -e "./apps/api[dev]"

api-lint:
	cd apps/api && python -m ruff check .

api-test:
	cd apps/api && python -m pytest

api-migrate: ## Apply database migrations inside the API container
	docker compose exec api alembic upgrade head

api-migration-check: ## Verify migrations apply, match models, and roll back on SQLite
	cd apps/api && ENVIRONMENT=test DATABASE_URL="sqlite+aiosqlite:///./ci-migration.db" AUTO_CREATE_SCHEMA=false alembic upgrade head
	cd apps/api && ENVIRONMENT=test DATABASE_URL="sqlite+aiosqlite:///./ci-migration.db" AUTO_CREATE_SCHEMA=false alembic check
	cd apps/api && ENVIRONMENT=test DATABASE_URL="sqlite+aiosqlite:///./ci-migration.db" AUTO_CREATE_SCHEMA=false alembic downgrade base
	rm -f apps/api/ci-migration.db

web-install: ## Install exact frontend dependencies
	npm --prefix apps/web ci

web-lint:
	npm --prefix apps/web run lint

web-typecheck:
	npm --prefix apps/web run typecheck

web-test:
	npm --prefix apps/web test

web-build:
	npm --prefix apps/web run build

# Mirrors the blocking CI jobs; the advisory audit/typecheck steps and the container
# smoke test still run only in CI.
check: api-lint api-test api-migration-check web-lint web-typecheck web-test web-build ## Run the blocking CI checks
