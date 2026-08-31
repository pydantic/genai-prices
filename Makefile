.DEFAULT_GOAL := all

.PHONY: .uv
.uv: ## Check that uv is installed
	@uv --version || echo 'Please install uv: https://docs.astral.sh/uv/getting-started/installation/'

.PHONY: .pre-commit
.pre-commit: ## Check that pre-commit is installed
	@pre-commit -V || echo 'Please install pre-commit: https://pre-commit.com/'

.PHONY: install
install: .uv .pre-commit ## Install the package, dependencies, and pre-commit for local development
	uv sync --frozen --all-packages --all-extras
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

.PHONY: build-prices
build-prices: ## Validate providers and build the authoring schema and v2 price data
	uv run -m prices build

.PHONY: package-data
package-data: ## Build static unit registries and v2 provider data for packages
	uv run -m prices package_data

.PHONY: build
build: build-prices package-data inject-providers ## Build v2 prices, package data, and the provider inventory

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

.PHONY: huggingface-get
huggingface-get: ## get huggingface prices
	uv run -m prices get_huggingface_prices

.PHONY: cloudflare-get
cloudflare-get: ## get cloudflare workers ai prices
	uv run -m prices get_cloudflare_prices

.PHONY: arcee-get
arcee-get: ## get arcee model prices
	uv run -m prices get_arcee_prices

.PHONY: cursor-get
cursor-get: ## get cursor model prices
	uv run -m prices get_cursor_prices

.PHONY: ovhcloud-get
ovhcloud-get: ## get ovhcloud ai endpoints prices
	uv run -m prices get_ovhcloud_prices

.PHONY: quicksilverpro-get
quicksilverpro-get: ## get quicksilver pro prices
	uv run -m prices get_quicksilverpro_prices

.PHONY: get-all-prices
get-all-prices: helicone-get openrouter-get litellm-get simonw-prices-get huggingface-get arcee-get cloudflare-get cursor-get ovhcloud-get quicksilverpro-get ## get all prices

.PHONE: update-price-discrepancies
update-price-discrepancies: ## update price discrepancies
	uv run -m prices update_price_discrepancies

.PHONE: get-update-price-discrepancies
get-update-price-discrepancies: get-all-prices update-price-discrepancies ## get and update price discrepancies

.PHONY: check-for-price-discrepancies
check-for-price-discrepancies: ## check for price discrepancies
	uv run -m prices check_for_price_discrepancies

.PHONY: detect-deprecated
detect-deprecated: ## Detect models that may be deprecated or removed
	uv run -m prices detect_deprecated

.PHONY: inject-providers
inject-providers: ## inject providers into README.md
	uv run -m prices inject_providers

.PHONY: typecheck
typecheck:
	uv run basedpyright

.PHONY: test
test: ## Run tests and collect coverage data
	uv run coverage run -m pytest
	uv run python tests/dataset/extract_usages.py
	@$(MAKE) coverage-report

.PHONY: testcov
testcov: test ## Run tests and generate an HTML coverage report
	@echo "building coverage html"
	@uv run coverage html

.PHONY: coverage-report
coverage-report: ## Report coverage for all Python code
	@uv run coverage report

.PHONY: test-all-python
test-all-python: ## Run tests on Python 3.10 to 3.14
	UV_PROJECT_ENVIRONMENT=.venv310 uv run --python 3.10 --all-extras --all-packages coverage run -p -m pytest
	UV_PROJECT_ENVIRONMENT=.venv311 uv run --python 3.11 --all-extras --all-packages coverage run -p -m pytest
	UV_PROJECT_ENVIRONMENT=.venv312 uv run --python 3.12 --all-extras --all-packages coverage run -p -m pytest
	UV_PROJECT_ENVIRONMENT=.venv313 uv run --python 3.13 --all-extras --all-packages coverage run -p -m pytest
	UV_PROJECT_ENVIRONMENT=.venv314 uv run --python 3.14 --all-extras --all-packages coverage run -p -m pytest
	@uv run coverage combine
	@$(MAKE) coverage-report

.PHONY: test-js
test-js: ## Build, typecheck, lint and test the JS package with coverage
	npm run ci

.PHONY: format-go
format-go: ## Format the Go package
	cd packages/go && gofmt -w $$(find . -name '*.go' -type f)

.PHONY: lint-go
lint-go: ## Lint the Go package
	cd packages/go && go run github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.10.1 run ./...

.PHONY: test-go
test-go: ## Test the Go package with the race detector and coverage
	cd packages/go && go test -race -coverprofile=coverage.out ./...
	cd packages/go && go tool cover -func=coverage.out
	@cd packages/go && go tool cover -func=coverage.out | \
		awk '/^total:/ && $$3 + 0 < 90 { print "Go coverage must be at least 90%"; exit 1 }'

.PHONY: all
all: build package-data format format-go lint lint-go typecheck testcov test-js test-go ## Run all builds, checks, and tests

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
