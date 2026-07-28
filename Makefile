REMOTE_HOST  ?= adapt-server
STAGING_DIR  ?= ~/apps/kira-staging
PROD_DIR     ?= ~/apps/kira-prod

# A deploy discards any hot-swap: the committed pointer is the declared active version.
POINTER      := active_version.json

STAGING_COMPOSE := docker-compose.staging.yml
PROD_COMPOSE    := docker-compose.prod.yml

.DEFAULT_GOAL := help
.PHONY: help lock sync test evals up down deploy-staging deploy-prod

help:
	@echo "Local"
	@echo "  make lock                     regenerate uv.lock"
	@echo "  make sync                     install the locked environment"
	@echo "  make test                     run the unit suite (no network)"
	@echo "  make evals                    run the eval gate against the real API"
	@echo "  make up                       bring the staging stack up locally"
	@echo "  make down                     tear it down"
	@echo ""
	@echo "Deploy"
	@echo "  make deploy-staging REF=<ref> deploy any ref to staging"
	@echo "  make deploy-prod              deploy main to production"

lock:
	uv lock

sync:
	uv sync --frozen

test:
	uv run pytest

up:
	GIT_COMMIT=$$(git rev-parse --short HEAD) HOST_GID=$$(id -g) \
	  docker compose -f $(STAGING_COMPOSE) up --build

down:
	docker compose -f $(STAGING_COMPOSE) down

# Staging takes any ref — that is what replaces a long-lived staging branch.
deploy-staging:
ifndef REF
	$(error REF is required, e.g. make deploy-staging REF=spec/001-brain-rules-engine)
endif
	ssh $(REMOTE_HOST) 'set -e; \
	  cd $(STAGING_DIR); \
	  git fetch --all --prune; \
	  git checkout -- company_brain/$(POINTER); \
	  git checkout --detach origin/$(REF) 2>/dev/null || git checkout --detach $(REF); \
	  GIT_COMMIT=$$(git rev-parse --short HEAD) HOST_GID=$$(id -g) \
	    docker compose -f $(STAGING_COMPOSE) up -d --build; \
	  echo "staging now at $$(git rev-parse --short HEAD)"'

# Production accepts main and nothing else, so it cannot be pointed at an
# unmerged branch by accident.
deploy-prod:
	ssh $(REMOTE_HOST) 'set -e; \
	  cd $(PROD_DIR); \
	  git fetch --all --prune; \
	  git checkout -- company_brain/$(POINTER); \
	  git checkout --detach origin/main; \
	  GIT_COMMIT=$$(git rev-parse --short HEAD) HOST_GID=$$(id -g) \
	    docker compose -f $(PROD_COMPOSE) up -d --build; \
	  echo "production now at $$(git rev-parse --short HEAD)"'

# The gate, as CI runs it. Spends real money; the runner stops rather than
# exceeding --max-cost-usd.
evals:
	uv run python evals/run_evals.py --runs 3 --concurrency 4 --max-cost-usd 2.50
