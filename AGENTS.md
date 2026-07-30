# AGENTS.md

This file provides guidance to AI coding agents working in this repository. `CLAUDE.md` is a symlink
to this file, so every harness reads the same instructions.

## Repository Overview

This is the GenAI Prices project - a database and tools for calculating LLM inference API pricing. The project includes:

- **Price Data**: YAML files in `prices/providers/` with pricing information for 30+ LLM providers
- **Unit Registry**: `prices/units.yml` defines every billable unit and its price key
- **Packages**: `packages/python/` (PyPI `genai-prices`) and `packages/js/` (npm `@pydantic/genai-prices`) —
  two implementations that must stay behaviourally identical
- **Data Pipeline**: Tools to build JSON schemas, validate data, and update from external sources
- **Price Sources**: Integration with Helicone, OpenRouter, LiteLLM, and other pricing sources

## Architecture

### Core Components

1. **Price Data Sources** (`prices/providers/*.yml`): YAML files containing model pricing information for each provider
2. **Unit Registry** (`prices/units.yml`): the vocabulary of billable units — every valid price key and
   extractor destination is derived from it
3. **Data Pipeline** (`prices/src/prices/`): Python modules that build, validate, and process pricing data
4. **Packages** (`packages/python/`, `packages/js/`): published libraries for end users to calculate costs
5. **External Data Integration**: Tools to pull and compare prices from external sources

### Key Directories

- `prices/`: Core pricing data and build tools
  - `providers/`: YAML files with provider-specific pricing
  - `units.yml`: the unit registry (see "Adding a unit" below before editing)
  - `src/prices/`: Python package for data processing
  - `new_data/v2/`: the **live** published data — `data.json`, `data_slim.json` and their schemas (generated)
  - `data.json`, `data_slim.json` + schemas: **frozen v1** compatibility snapshots (see "Pricing Data")
- `packages/python/`, `packages/js/`: published packages. `data.py`/`data.ts` and `data_units.py`/`dataUnits.ts`
  are generated — never hand-edit them
- `tests/`: Python test suite; JS tests live in `packages/js/src/__tests__/`
- `specs/data-driven-unit-registry/`: authoritative design docs for the unit registry and the v1/v2/v3
  contract rules. Read these before changing anything about units or published artifacts
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
make test         # Run the Python tests with coverage (does NOT run the JS suite)
make testcov      # Run tests and generate HTML coverage report
npm run ci        # Build and test the JS package — no Make target runs this
```

`make all` covers the Python side only. Run `npm run ci` yourself before pushing anything that
touches `packages/js/` or regenerates package data.

### Building and Data Processing

```bash
make build        # build-prices + package-data + inject-providers — use this one
make build-prices # Validate providers and write prices/new_data/v2/* + prices/providers/.schema.json
make package-data # Regenerate the bundled data in packages/python/ and packages/js/
```

Always run `make build`, not `make build-prices` alone. The installed packages read their **bundled**
data (`packages/python/genai_prices/data.py`, `packages/js/src/data.ts`), which only `package-data`
regenerates — so a `calc_price` check run after `build-prices` verifies stale data.

### Price Data Management

```bash
make get-all-prices                    # Download prices from all external sources
make helicone-get                      # Get Helicone prices
make openrouter-get                    # Get OpenRouter prices
make litellm-get                       # Get LiteLLM prices
make simonw-prices-get                 # Get Simon Willison's prices
make huggingface-get                   # Get HuggingFace prices
make ovhcloud-get                      # Get OVHcloud AI Endpoints prices
make get-update-price-discrepancies    # Download and update price discrepancies
make check-for-price-discrepancies     # Check for price discrepancies
make detect-deprecated                 # Detect models that may be deprecated or removed
make collapse-models                   # Collapse duplicate similar models
```

`make help` lists every target. These importers run against live third-party APIs and nothing in CI
exercises them, so they break silently when an upstream schema changes — if one returns suspiciously
little, suspect the importer before the data.

## Important Notes

### Pricing Data

- **v2 is the live feed.** `prices/new_data/v2/data.json` is what the published packages auto-update
  from, and it goes live on merge to `main` — independent of any package release.
- **v1 is frozen.** `prices/data.json` and `prices/data_slim.json` are compatibility snapshots for
  pre-0.1.0 clients. No build step writes them any more, and they receive no provider, model or price
  updates. Don't regenerate them, don't hand-edit them, and don't treat their stale `prices_checked`
  dates as a bug.
- **NEVER** hand-edit any generated file: the v2 payloads and schemas, `prices/providers/.schema.json`,
  or the bundled `data.py` / `data.ts` / `data_units.py` / `dataUnits.ts`. Edit the provider YAML or
  `prices/units.yml` and run `make build`.
- Published artifact URLs must not change — new contracts go in a new `prices/new_data/v<version>/`
  directory rather than moving or renaming existing files.
- When updating prices in YAML files, always update the `prices_checked` field to current date
- Add `price_comments` to explain changes and provide references

### Authoring provider YAML

- The valid `prices:` keys and extractor `dest:` values are **derived from `prices/units.yml`**, not
  hardcoded anywhere. `prices/providers/.schema.json` is the generated list; your IDE reads it via the
  `# yaml-language-server:` header, but on the CLI read `units.yml` directly.
- **Not every price key is per-million-tokens.** `_mtok` is per 1M, `_kcount` is per 1,000 (e.g.
  `requests_kcount`, `web_searches_kcount`), `_mchars` per 1M characters, `_hours` per 3,600 seconds,
  `_gpixels` per 1e9, `_kpages` per 1,000. Putting a per-Mtok figure under a `_kcount` key is valid
  YAML and silently wrong by 1000×.
- Prices must cover their **ancestors and joins**: a model priced with `cache_write_1h_mtok` also needs
  `cache_write_mtok`, and so on. `make build` enforces this; the error names the missing key.

### Adding a unit

**Adding a unit to `prices/units.yml` is a v3 change, not a v2 price update.** `make build` regenerates
`prices/new_data/v2/data.schema.json` from the registry, so adding a unit silently widens the published
v2 contract — and clients that haven't upgraded warn-and-drop the unknown key rather than failing, which
means silently under-priced usage in production. Nothing currently blocks this; the constraint is stated
in `specs/data-driven-unit-registry/phase-1-static-unit-registry-release/code-spec.md` and is a
maintainer responsibility. Read that spec first, and see the header comment in `units.yml` for the
closure rules.

### Development Workflow

- Use `uv` for dependency management (not pip/conda), `npm` for the JS workspace
- The pre-commit `build` hook fires on any change under `prices/` and rewrites **nine** paths:
  `prices/providers/.schema.json`, the four `prices/new_data/v2/*` files, `data.py`, `data_units.py`,
  `data.ts`, `dataUnits.ts`, plus `README.md` (provider list). Your first `git commit` will abort after
  it rewrites them — re-stage the regenerated files and commit again. Never reach for `--no-verify`:
  that hook is the only thing keeping the published data in sync with the YAML.
- Run `make build` after editing anything under `prices/`
- Always run the full test suite before submitting changes

### Testing

- Python tests use pytest and are in `tests/`; JS tests are in `packages/js/src/__tests__/` and run
  via `npm run ci`
- CI enforces **100% Python coverage** on `packages/python/**` and `tests/**`. Local `make test` runs
  `coverage report --fail-under=0`, so a green `make test` does not mean the coverage gate will pass.
- `make test` also runs `tests/dataset/extract_usages.py`, which **rewrites** `tests/dataset/usages.json`
  and then fails if it changed. That is the cross-language golden dataset — the regenerated file is
  usually the correct new state, so inspect the diff and commit it rather than reverting. Because it
  writes before comparing, a second `make test` always passes; don't read that as a fix.
- Price changes are pinned by assertions in `tests/test_price_calc.py` and `tests/test_price_regressions.py`.
  Update the expected values; don't weaken or delete the assertion.
- Use `make test-all-python` to test across Python 3.10-3.14

### Python/JS parity

The two packages are independent implementations of the same behaviour and are the easiest place to
introduce drift. Any change to pricing, extraction, matching or unit handling must land on both sides.
`tests/dataset/usages.json` is generated by Python and asserted by JS, so it catches arithmetic drift on
the models real data covers — but it pins a single UTC instant and only the units shipped prices use, so
it does not catch constraint-resolution, matching, warning or error-shape divergence.

### Code Style

- Code formatted with ruff (single quotes, 120 char line length)
- Type checking with basedpyright in strict mode
- Follow existing patterns in the codebase

## Pull Requests

After opening or updating a PR, don't go idle until it's genuinely in its desired end state. After
pushing, poll (~every 30s) until **both**:

- CI is green, and
- every reviewer comment (cubic included) is addressed or explicitly dismissed.

A PR with unresolved review threads is not mergeable. Resolve each one — fix and reply, or dismiss
with a reason — except threads left intentionally as informational (not meant to be resolved).
