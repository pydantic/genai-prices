# AGENTS.md

This file provides guidance to AI coding agents working in this repository. `CLAUDE.md` is a symlink
to this file, so every harness reads the same instructions.

## Repository Overview

This is the GenAI Prices project - a database and tools for calculating LLM inference API pricing. The project includes:

- **Price Data**: YAML files in `prices/providers/` with pricing information for 30+ LLM providers
- **Unit Registry**: `prices/units.yml` defines every billable unit and its price key
- **Packages**: `packages/python/` (PyPI `genai-prices`), `packages/js/` (npm `@pydantic/genai-prices`),
  `packages/go/` (Go module `github.com/pydantic/genai-prices/packages/go`) and `packages/rust/` (crate
  `genai-prices`) — four implementations that must stay behaviourally identical (see "Python/JS/Go/Rust parity")
- **Data Pipeline**: Tools to build JSON schemas, validate data, and update from external sources
- **Price Sources**: Integration with Helicone, OpenRouter, LiteLLM, and other pricing sources

## Architecture

### Core Components

1. **Price Data Sources** (`prices/providers/*.yml`): YAML files containing model pricing information for each provider
2. **Unit Registry** (`prices/units.yml`): the vocabulary of billable units — every valid price key and
   extractor destination is derived from it
3. **Data Pipeline** (`prices/src/prices/`): Python modules that build, validate, and process pricing data
4. **Packages** (`packages/python/`, `packages/js/`, `packages/go/`, `packages/rust/`): published libraries for end
   users to calculate costs
5. **External Data Integration**: Tools to pull and compare prices from external sources

### Key Directories

- `prices/`: Core pricing data and build tools
  - `providers/`: YAML files with provider-specific pricing
  - `units.yml`: the unit registry (see "Adding a unit" below before editing)
  - `src/prices/`: Python package for data processing
  - `new_data/v2/`: the **live** published data — `data.json`, `data_slim.json` and their schemas (generated)
  - `data.json`, `data_slim.json` + schemas: **frozen v1** compatibility snapshots (see "Pricing Data")
- `packages/python/`, `packages/js/`, `packages/go/`, `packages/rust/`: published packages. Their provider data
  (`data.py`, `data.ts`, `internal/data/prices.json`, `data/prices.json`) and unit data (`data_units.py`,
  `dataUnits.ts`, `data_units.go`, `src/data_units.rs`) are generated — never hand-edit them
- `tests/`: Python test suite; JS tests live in `packages/js/src/__tests__/`, Go tests in `packages/go/*_test.go`,
  Rust tests in `packages/rust/tests/`
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
make test         # Run the Python tests with coverage (does NOT run the JS, Go or Rust suites)
make testcov      # Run tests and generate HTML coverage report
npm run ci        # Build and test the JS package
make format-go    # Format the Go package with gofmt
make lint-go      # Lint the Go package with golangci-lint
make test-go      # Run the Go tests with the race detector; fails below 90% coverage
make format-rust  # Format the Rust crate with rustfmt
make lint-rust    # Check rustfmt and run clippy with warnings as errors
make test-rust    # Run the Rust tests with cargo-llvm-cov; fails below 95% line coverage
```

`make all` covers Python, JavaScript, Go and Rust. Run `npm run ci` directly to verify only JavaScript, `make test-go`
to verify only Go, and `make test-rust` to verify only Rust.

### Building and Data Processing

```bash
make build        # build-prices + package-data + inject-providers — use this one
make build-prices # Validate providers and write prices/new_data/v2/* + prices/providers/.schema.json
make package-data # Regenerate the bundled data in packages/python/, packages/js/, packages/go/ and packages/rust/
```

Always run `make build`, not `make build-prices` alone. The installed packages read their **bundled**
data (`packages/python/genai_prices/data.py`, `packages/js/src/data.ts`, `packages/go/internal/data/prices.json`,
`packages/rust/data/prices.json`), which only `package-data` regenerates — so a `calc_price` check run after
`build-prices` verifies stale data.

### Price Data Management

```bash
make get-all-prices                    # Download prices from all external sources
make helicone-get                      # Get Helicone prices
make openrouter-get                    # Get OpenRouter prices
make litellm-get                       # Get LiteLLM prices
make simonw-prices-get                 # Get Simon Willison's prices
make huggingface-get                   # Get HuggingFace prices
make ovhcloud-get                      # Get OVHcloud AI Endpoints prices
make quicksilverpro-get                # Get QuickSilver Pro prices
make get-update-price-discrepancies    # Download and update price discrepancies
make check-for-price-discrepancies     # Check for price discrepancies
make detect-deprecated                 # Detect models that may be deprecated or removed
make collapse-models                   # Collapse duplicate similar models
```

`make help` lists every target. These importers run against live third-party APIs and nothing in CI
exercises them, so they break silently when an upstream schema changes — if one returns suspiciously
little, suspect the importer before the data. The importers that rewrite tracked `prices/providers/*.yml`
(`huggingface-get`, `ovhcloud-get`, `quicksilverpro-get`) exit non-zero instead of writing when the upstream
catalog is empty or has shrunk by more than half (`prices/src/prices/write_guard.py`); set
`PRICES_ALLOW_MODEL_COUNT_DROP=1` to override a genuine catalog cut.

## Important Notes

### Pricing Data

- **v2 is the live feed.** `prices/new_data/v2/data.json` is what the published packages auto-update
  from, and it goes live on merge to `main` — independent of any package release.
- **v1 is frozen.** `prices/data.json`, `prices/data_slim.json` and their two schemas are compatibility
  snapshots for pre-0.1.0 clients. No build step writes them any more, and they receive no provider,
  model or price updates. Don't regenerate them, don't hand-edit them, and don't treat their stale
  `prices_checked` dates as a bug. `tests/test_frozen_v1_data.py` pins their sha256 digests, so an edit
  fails the test suite — because no build step rewrites them, that test is the only thing that catches it.
- **NEVER** hand-edit any generated file: the v2 payloads and schemas, `prices/providers/.schema.json`,
  or the bundled `data.py` / `data.ts` / `prices.json` / `data_units.py` / `dataUnits.ts` / `data_units.go`.
  Edit the provider YAML or `prices/units.yml` and run `make build`. The pre-commit `build` hook regenerates
  all of these and fails when the result differs, so CI catches an edit to any of them.
- Every generated artifact is marked `linguist-generated` in `.gitattributes`, so GitHub collapses its
  diff. Review the provider YAML and `units.yml`; trust the build hook and the digest test for the rest.
- Published artifact URLs must not change — new contracts go in a new `prices/new_data/v<version>/`
  directory rather than moving or renaming existing files.
- **Never overwrite a `prices:` block when a provider changes its rates.** Editing those values in
  place re-prices every past request at the new rate — a request from before the change gets billed
  at today's price. Add a dated conditional price entry instead: make `prices:` a list, keep the
  existing rates as the first entry with no `constraint`, and append the new rates under
  `constraint: { start_date: <date the new price took effect> }`. All three engines take the **last**
  matching entry, so the dated entry goes at the end. `openai.yml` (o3) and `anthropic.yml`
  (1M-context surcharge) show the shape. Overwrite in place only to correct a value that was already
  wrong when it was written — a correction has no history worth keeping. The `/add-price-model` skill
  covers the full procedure.
- When a model has `price_variants`, verify every tier separately when its standard rates change.
  The rates a variant lists are absolute; omitted keys inherit standard prices for that date. Preserve existing
  variant entries and prepend dated entries for changed tier rates: variants use the first matching
  value per price key. Record a source confirming any tier whose rates stayed unchanged, and test
  each affected context before and after the change in Python, JavaScript, Go and Rust.
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
- An extractor that maps `completion_tokens` must also map `output_reasoning_tokens`. OpenAI-compatible
  chat responses count reasoning tokens inside `completion_tokens` and report the breakdown under
  `completion_tokens_details.reasoning_tokens`; an unmapped response field is dropped with no warning, so
  omitting it silently loses the breakdown. `make build` enforces this and names the provider and flavor.
  `openai.yml`'s `chat` extractor is the reference shape to copy for any OpenAI-compatible provider —
  `huggingface_*.yml` and `ovhcloud.yml` are generated copies of it.

### Adding a unit

**Adding a unit to `prices/units.yml` is a v3 change, not a v2 price update.** `make build` regenerates
`prices/new_data/v2/data.schema.json` from the registry, so adding a unit silently widens the published
v2 contract — and clients that haven't upgraded warn-and-drop the unknown key rather than failing, which
means silently under-priced usage in production. Nothing currently blocks this; the constraint is stated
in `specs/data-driven-unit-registry/phase-1-static-unit-registry-release/code-spec.md` and is a
maintainer responsibility. Read that spec first, and see the header comment in `units.yml` for the
closure rules.

### Development Workflow

- Use `uv` for dependency management (not pip/conda), `npm` for the JS workspace, `go` modules for `packages/go/`
  and `cargo` for `packages/rust/`
- `make build` needs a Go toolchain on `PATH`: `package-data` runs `gofmt` on the generated `data_units.go`. It does
  not need a Rust toolchain: the generated `data_units.rs` is excluded from rustfmt
- The pre-commit `build` hook fires on any change under `prices/` and rewrites **fourteen** paths:
  `prices/providers/.schema.json`, the four `prices/new_data/v2/*` files, `data.py`, `data_units.py`,
  `data.ts`, `dataUnits.ts`, `packages/go/internal/data/prices.json`, `packages/go/data_units.go`,
  `packages/rust/data/prices.json`, `packages/rust/src/data_units.rs`, plus `README.md` (provider list). Your first
  `git commit` will abort after it rewrites them — re-stage the regenerated files and commit again. Never reach
  for `--no-verify`: that hook is the only thing keeping the published data in sync with the YAML.
- Run `make build` after editing anything under `prices/`
- Always run the full test suite before submitting changes

### Testing

- Python tests use pytest and are in `tests/`; JS tests are in `packages/js/src/__tests__/` and run
  via `npm run ci`; Go tests are `packages/go/*_test.go` and run via `make test-go`; Rust tests are
  `packages/rust/tests/*.rs` and run via `make test-rust`
- CI and local `make test` enforce **100% coverage** across `packages/python/**`, `prices/src/**`,
  and `tests/**`. CI and local `make test-go` enforce **90% coverage** of `packages/go/`, and `make test-rust`
  **95% line coverage** of `packages/rust/`.
- **Never hand-edit `tests/dataset/usages.json` or add synthetic feature cases to it.** It is the
  cross-language golden dataset generated by `tests/dataset/extract_usages.py` from recorded raw bodies;
  synthetic behavior belongs in focused Python, JavaScript, Go and Rust tests. `tests/test_dataset.py` compares in
  memory and fails if the file is stale; regenerate with `python tests/dataset/extract_usages.py` and
  commit the diff.
- Price changes are pinned by assertions in `tests/test_price_calc.py`, `tests/test_price_regressions.py`,
  `packages/js/src/__tests__/` and `packages/go/api_test.go`. Update the expected values; don't weaken or delete
  the assertion.
- Use `make test-all-python` to test across Python 3.10-3.14

### Python/JS/Go/Rust parity

The four packages are independent implementations of the same behaviour and are the easiest place to
introduce drift. Any change to pricing, extraction, matching or unit handling must land in all four. The
runtime data updater and the CLI exist only in Python and JS; Go callers load fresh data with
`NewCalculatorFromJSON` and Rust callers with `Calculator::from_json`.
`tests/dataset/usages.json` is generated by Python and asserted by JS, Go (`packages/go/dataset_test.go`) and Rust
(`packages/rust/tests/dataset.rs`),
so it catches arithmetic drift on the models real data covers — but it pins a single UTC instant and only the
units shipped prices use, so it does not catch constraint-resolution, matching, warning or error-shape divergence.
`packages/go/parity_test.go` covers matching, constraint resolution, tiered pricing, usage decomposition and
usage extraction for Go against synthetic provider data. It asserts hardcoded expectations, not the other
engines' output, so update it together with the matching Python and JS tests.
`packages/rust/tests/parity.rs` is a line-for-line port of it; keep the two in step. Rust ports the Go price
pins that exercise engine behaviour (tier and batch variants, long-context boundaries, API-URL matching, array-match
extraction) in `packages/rust/tests/price_context.rs` and `packages/rust/tests/api.rs`, but not the per-model pins;
when a ported pin's price changes, update the Go and Rust expectations together.

### Code Style

- Code formatted with ruff (single quotes, 120 char line length)
- Type checking with basedpyright in strict mode
- Follow existing patterns in the codebase

## Releasing

Create a GitHub release with a `vX.Y.Z` tag; CI publishes the Python and JS packages from it and creates the
matching `packages/go/vX.Y.Z` tag for the Go module. The version lives only in the tag -
`packages/python/pyproject.toml` is `dynamic` (uv-dynamic-versioning) and the `0.0.0` in
`packages/js/package.json` is a placeholder the release job overwrites. Never add a version bump to a PR. See
`RELEASE.md`.

## Pull Requests

After opening or updating a PR, don't go idle until it's genuinely in its desired end state. After
pushing, poll (~every 30s) until **both**:

- CI is green, and
- every reviewer comment (cubic included) is addressed or explicitly dismissed.

A PR with unresolved review threads is not mergeable. Resolve each one — fix and reply, or dismiss
with a reason — except threads left intentionally as informational (not meant to be resolved).
