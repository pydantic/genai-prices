.DEFAULT_GOAL := all

.PHONY: .uv
.uv: ## Check that uv is installed
	@uv --version || echo 'Please install uv: https://docs.astral.sh/uv/getting-started/installation/'

.PHONY: .pre-commit
.pre-commit: ## Check that pre-commit is installed
	@pre-commit -V || echo 'Please install pre-commit: https://pre-commit.com/'

.PHONY: install
install: .uv .pre-commit ## Install the package, dependencies, and pre-commit for local development
	uv sync --frozen --all-packages
	pre-commit install --install-hooks

.PHONY: sync
sync: .uv ## Update local packages and uv.lock
	uv sync --all-packages

.PHONY: format
format: ## Format the code
	uv run ruff format
	uv run ruff check --fix --fix-only

.PHONY: lint
lint: ## Lint the code
	uv run ruff format --check
	uv run ruff check

.PHONY: build
build: ## Build JSON Schema for data and validate and write data to prices/data.json
	uv run -m prices build


.PHONY: collapse-models
collapse-models: ## Collapse duplicate similar models
	uv run -m prices collapse

.PHONY: helicone-get
helicone-get: ## get helicone prices
	./prices/helicone_get/pull.sh
	cd prices/helicone_get && deno task run

.PHONY: openrouter-get
openrouter-get: ## get openrouter prices
		uv run -m prices get_openrouter_prices

.PHONY: litellm-get
litellm-get: ## get litellm prices
	uv run -m prices get_litellm_prices

.PHONY: simonw-prices-get
simonw-prices-get: ## get simonw-prices
		uv run -m prices get_simonw_prices

.PHONY: get-all-prices
get-all-prices: helicone-get openrouter-get litellm-get simonw-prices-get ## get all prices

.PHONE: update-price-discrepancies
update-price-discrepancies: ## update price discrepancies
	uv run -m prices update_price_discrepancies


.PHONE: get-update-price-discrepancies
get-update-price-discrepancies: get-all-prices update-price-discrepancies ## get and update price discrepancies

.PHONY: typecheck
typecheck:
	@# PYRIGHT_PYTHON_IGNORE_WARNINGS avoids the overhead of making a request to github on every invocation
	PYRIGHT_PYTHON_IGNORE_WARNINGS=1 uv run pyright

.PHONY: test
test: ## Run tests and collect coverage data
	uv run coverage run -m pytest
	@uv run coverage report

.PHONY: testcov
testcov: test ## Run tests and generate an HTML coverage report
	@echo "building coverage html"
	@uv run coverage html

.PHONY: all
all: format lint typecheck testcov ## Run code formatting, linting, static type checks, and tests with coverage report generation

.PHONY: help
help: ## Show this help (usage: make help)
	@echo "Usage: make [recipe]"
	@echo "Recipes:"
	@awk '/^[a-zA-Z0-9_-]+:.*?##/ { \
		helpMessage = match($$0, /## (.*)/); \
		if (helpMessage) { \
			recipe = $$1; \
			sub(/:/, "", recipe); \
			printf "  \033[36m%-20s\033[0m %s\n", recipe, substr($$0, RSTART + 3, RLENGTH); \
		} \
	}' $(MAKEFILE_LIST)
