# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is the GenAI Prices project - a database and tools for calculating LLM inference API pricing. The project includes:

- **Price Data**: YAML files in `prices/providers/` with pricing information for 16+ LLM providers
- **Python Package**: Located in `packages/python/` - a Python library for calculating costs
- **Data Pipeline**: Tools to build JSON schemas, validate data, and update from external sources
- **Price Sources**: Integration with Helicone, OpenRouter, LiteLLM, and other pricing sources

## Architecture

### Core Components

1. **Price Data Sources** (`prices/providers/*.yml`): YAML files containing model pricing information for each provider
2. **Data Pipeline** (`prices/src/prices/`): Python modules that build, validate, and process pricing data
3. **Python Package** (`packages/python/`): Published package for end users to calculate costs
4. **External Data Integration**: Tools to pull and compare prices from external sources

### Key Directories

- `prices/`: Core pricing data and build tools
  - `providers/`: YAML files with provider-specific pricing
  - `src/prices/`: Python package for data processing
  - `data.json` and `data_slim.json`: Built JSON files (DO NOT EDIT DIRECTLY)
- `packages/python/`: Published Python package for users
- `tests/`: Python Test suite
- `scratch/`: Development/testing files IGNORE THESE FILES

## Development Commands

### Setup
```bash
make install      # Install dependencies and pre-commit hooks
make sync         # Update local packages and uv.lock
```

### Core Development
```bash
make format       # Format code with ruff
make lint         # Check code style and linting
make typecheck    # Run static type checking with basedpyright
make test         # Run tests with coverage
make testcov      # Run tests and generate HTML coverage report
```

### Building and Data Processing

```bash
make build-prices # Build JSON schema and validate/write data to prices/data.json
make package-data # Prepare data for packages
```

### Price Data Management

```bash
make get-all-prices                    # Download prices from all external sources
make helicone-get                      # Get Helicone prices
make openrouter-get                    # Get OpenRouter prices
make litellm-get                       # Get LiteLLM prices
make simonw-prices-get                 # Get Simon Willison's prices
make get-update-price-discrepancies    # Download and update price discrepancies
make check-for-price-discrepancies     # Check for price discrepancies
```


## Important Notes

### Pricing Data
- **NEVER** edit `prices/data.json` or `prices/data_slim.json` directly - they are generated files
- When updating prices in YAML files, always update the `prices_checked` field to current date
- Add `price_comments` to explain changes and provide references
- URLs for `data.json` and `data_slim.json` must not change (used by auto-update feature)

### Development Workflow
- Use `uv` for dependency management (not pip/conda)
- Pre-commit hooks will automatically update JSON files when YAML prices change
- Run `make build` after editing provider YAML files
- Always run the full test suite before submitting changes

### Testing
- Tests use pytest with coverage reporting
- Test files are in `tests/` directory
- Use `make test-all-python` to test across Python 3.9-3.13

### Code Style
- Code formatted with ruff (single quotes, 120 char line length)
- Type checking with basedpyright in strict mode
- Follow existing patterns in the codebase
