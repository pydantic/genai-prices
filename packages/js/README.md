# genai-prices package (JS/TS)

Library and CLI for calculating LLM API prices, supporting browser, Node.js and other environments.

## Features

- **Sync API**: Fast, local price calculation using embedded data. Works in browser, Node.js, Cloudflare, Deno, etc.
- **Async API**: Fetches and caches price data from GitHub, works in browser, Node.js, Cloudflare, Deno, etc.
- **Environment-agnostic design**: Sync/async distinction is about API style, not environment.
- **Smart provider and model matching** with flexible options.
- **CLI** for quick price calculations with auto-update support.
- **Browser support** with a single bundle and test page.

## API Usage

The library provides separated input and output pricing, giving you detailed breakdown of costs:

- `result.total_price` - Total cost for the request
- `result.input_price` - Cost for input/prompt tokens
- `result.output_price` - Cost for output/completion tokens

### Node.js & Browser (Library)

```js
import { calcPriceSync, calcPriceAsync } from '@pydantic/genai-prices'

const usage = { input_tokens: 1000, output_tokens: 100 }

// Sync (works everywhere, including browser)
const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
if (result) {
  console.log(
    `$${result.total_price} (input: $${result.input_price}, output: $${result.output_price})`,
    result.provider.name,
    result.model.name,
  )
} else {
  console.log('No price found for this model/provider combination')
}

// Async (works everywhere)
const asyncResult = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
if (asyncResult) {
  console.log(
    `$${asyncResult.total_price} (input: $${asyncResult.input_price}, output: $${asyncResult.output_price})`,
    asyncResult.provider.name,
    asyncResult.model.name,
  )
} else {
  console.log('No price found for this model/provider combination')
}
```

### Browser (Direct Bundle)

```js
import { calcPriceSync, calcPriceAsync } from './dist/index.js'
const usage = { input_tokens: 1000, output_tokens: 100 }
const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
if (result) {
  console.log(
    `$${result.total_price} (input: $${result.input_price}, output: $${result.output_price})`,
    result.provider.name,
    result.model.name,
  )
}
```

### Global CLI Installation

You can install the CLI globally to use the `genai-prices` command from anywhere:

```bash
npm install -g @pydantic/genai-prices
```

After installing globally, you can run:

```bash
genai-prices calc gpt-4 --input-tokens 1000 --output-tokens 500
genai-prices list
```

### CLI

After global installation, you can use the CLI as follows:

```bash
# Basic usage
genai-prices gpt-3.5-turbo --input-tokens 1000 --output-tokens 100

# With auto-update (fetches latest prices from GitHub)
genai-prices gpt-3.5-turbo --input-tokens 1000 --output-tokens 100 --auto-update

# Specify provider explicitly
genai-prices openai:gpt-3.5-turbo --input-tokens 1000 --output-tokens 100

# List available providers and models
genai-prices list
genai-prices list openai
```

### Provider Matching

The library uses intelligent provider matching:

1. **Explicit provider**: Use `providerId` parameter or `provider:model` format
2. **Model-based matching**: Uses provider's `model_match` logic (e.g., OpenAI matches models starting with "gpt-")
3. **Fallback**: Tries to match based on model name patterns

**Best practices:**

- Always specify `providerId` if you know it (e.g., `openai`, `google`, etc.) for best results
- Use `provider:model` format in CLI for explicit provider selection
- The async API with `--auto-update` provides the most up-to-date pricing

### Error Handling

The library returns `null` when a model or provider is not found, rather than throwing errors. This makes it easier to handle cases where pricing information might not be available:

```js
import { calcPriceSync, calcPriceAsync } from '@pydantic/genai-prices'

const usage = { input_tokens: 1000, output_tokens: 100 }

// Returns null if model/provider not found
const result = calcPriceSync(usage, 'non-existent-model')
if (result === null) {
  console.log('No pricing information available for this model')
} else {
  console.log(`Total Price: $${result.total_price} (input: $${result.input_price}, output: $${result.output_price})`)
}

// Async version also returns null
const asyncResult = await calcPriceAsync(usage, 'non-existent-model', { providerId: 'unknown-provider' })
if (asyncResult === null) {
  console.log('No pricing information available for this model/provider combination')
} else {
  console.log(
    `Total Price: $${asyncResult.total_price} (input: $${asyncResult.input_price}, output: $${asyncResult.output_price})`,
  )
}
```

**TypeScript users**: The return type is `PriceCalculation | null` (exported as `PriceCalculationResult`).

## Testing

### Node.js Test

Run:

```bash
node tests/test-error-handling.js
```

This tests error handling, sync/async API, and providerId usage.

### Browser Test

1. Build the package: `npm run build`
2. Serve the directory: `npx serve .` or `python3 -m http.server`
3. Open `tests/test-browser.html` in your browser.
4. Enter a provider (e.g., `openai`) and model (e.g., `gpt-3.5-turbo`) and run the test.

## Architecture

### Folder Structure

```
src/
├── sync/
│   └── calcPriceSync.ts      # Sync API implementation
├── async/
│   └── calcPriceAsync.ts     # Async API implementation
├── dataLoader.ts             # Data loader (sync + async)
├── index.ts                  # Entry point (exports both sync + async)
├── cli.ts                    # CLI tool
├── types.ts                  # Shared types (snake_case, matches JSON)
├── matcher.ts                # Shared matching logic
├── priceCalc.ts              # Shared price calculation
└── __tests__/                # Tests
```

### Design Principles

- **Environment-agnostic APIs**: Sync/async is about API style, not environment
- **Single data loader**: Handles all environments with embedded data for sync and remote fetch for async
- **Cross-environment compatibility**: Both sync and async APIs can be used in Node.js, browser, Cloudflare, etc.
- **No mapping needed**: All types and data use snake_case, matching the JSON schema

## Troubleshooting

### Common Issues

- **No price found (returns null)**:
  - Make sure you specify the correct `providerId` (e.g., `openai`)
  - Try using `provider:model` format in CLI
  - Use `--auto-update` flag to fetch latest data
  - Check that the model name is correct and supported by the provider
- **Build errors**: Ensure you have run the build and that your data is up to date.

### Provider Matching Examples

```bash
# These should work with auto-update
genai-prices gpt-3.5-turbo --auto-update
genai-prices claude-3-5-sonnet --auto-update
genai-prices gemini-1.5-pro --auto-update

# Explicit provider specification
genai-prices openai:gpt-3.5-turbo
genai-prices anthropic:claude-3-5-sonnet
genai-prices google:gemini-1.5-pro
```

## Maintainers

- When adding new features, keep sync and async logic in separate files
- Only import Node.js built-ins in Node-only files if absolutely necessary
- Use the main entry for all environments
- All types and data should use snake_case to match the JSON schema
- Provider matching logic is in `matcher.ts` and should be environment-agnostic
