# genai-prices (JS/TS)

Universal library and CLI for calculating LLM API prices, supporting Node.js, browser, and other environments.

## Features

- **Sync API** (Node.js only): Fast, local price calculation using local data file.
- **Async API** (Universal): Fetches and caches price data from GitHub, works in browser, Node.js, Cloudflare, etc.
- **Environment-agnostic design**: Sync/async distinction is about API style, not environment.
- **Smart provider and model matching** with flexible options.
- **CLI** for quick price calculations with auto-update support.
- **Browser support** with a dedicated bundle and test page.

## Usage

### Node.js (Library)

```js
import { calcPriceSync, calcPriceAsync } from '@pydantic/genai-prices'

const usage = { inputTokens: 1000, outputTokens: 100 }

// Sync (Node.js only) - requires local data.json
const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
console.log(result.price, result.provider.name, result.model.name)

// Async (works everywhere) - fetches from GitHub
const asyncResult = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
console.log(asyncResult.price, asyncResult.provider.name, asyncResult.model.name)
```

### Browser (Library)

```js
import { calcPriceAsync } from './dist/browser.js'
const usage = { inputTokens: 1000, outputTokens: 100 }
const result = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
console.log(result.price, result.provider.name, result.model.name)
```

### CLI

```bash
# Basic usage
node dist/cli.js gpt-3.5-turbo --input-tokens 1000 --output-tokens 100

# With auto-update (fetches latest prices from GitHub)
node dist/cli.js gpt-3.5-turbo --input-tokens 1000 --output-tokens 100 --auto-update

# Specify provider explicitly
node dist/cli.js openai:gpt-3.5-turbo --input-tokens 1000 --output-tokens 100

# List available providers and models
node dist/cli.js list
node dist/cli.js list openai
```

### Provider Matching

The library uses intelligent provider matching:

1. **Explicit provider**: Use `providerId` parameter or `provider:model` format
2. **Model-based matching**: Uses provider's `modelMatch` logic (e.g., OpenAI matches models starting with "gpt-")
3. **Fallback**: Tries to match based on model name patterns

**Best practices:**

- Always specify `providerId` if you know it (e.g., `openai`, `google`, etc.) for best results
- Use `provider:model` format in CLI for explicit provider selection
- The async API with `--auto-update` provides the most up-to-date pricing

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
│   └── calcPriceSync.ts      # Sync API implementation (any environment)
├── async/
│   └── calcPriceAsync.ts     # Async API implementation (any environment)
├── dataLoader.node.ts        # Node.js data loader (sync + async)
├── dataLoader.browser.ts     # Browser data loader (async only)
├── index.ts                  # Node.js entry (exports both sync + async)
├── index.browser.ts          # Browser entry (exports async only)
├── cli.ts                    # CLI tool
├── types.ts                  # Shared types
├── matcher.ts                # Shared matching logic
├── priceCalc.ts              # Shared price calculation
└── __tests__/                # Tests
```

### Design Principles

- **Environment-agnostic APIs**: Sync/async is about API style, not environment
- **Environment-specific data loaders**: Each environment gets appropriate data loading
- **Universal compatibility**: Both sync and async APIs can be used in Node.js, browser, Cloudflare, etc.
- **Clean separation**: Data loaders are environment-specific, but APIs are not

## Troubleshooting

### Common Issues

- **Provider not found**:
  - Make sure you specify the correct `providerId` (e.g., `openai`)
  - Try using `provider:model` format in CLI
  - Use `--auto-update` flag to fetch latest data
- **Sync API in browser**: Not supported. Use only the async API in browser environments.
- **Build errors**: Ensure you have the latest data.json file in the dist directory.

### Provider Matching Examples

```bash
# These should work with auto-update
node dist/cli.js gpt-3.5-turbo --auto-update
node dist/cli.js claude-3-5-sonnet --auto-update
node dist/cli.js gemini-1.5-pro --auto-update

# Explicit provider specification
node dist/cli.js openai:gpt-3.5-turbo
node dist/cli.js anthropic:claude-3-5-sonnet
node dist/cli.js google:gemini-1.5-pro
```

## Maintainers

- When adding new features, keep sync and async logic in separate files
- Only import Node.js built-ins in Node-only files
- Use the browser entry for browser bundles
- Data loaders should handle snake_case to camelCase conversion
- Provider matching logic is in `matcher.ts` and should be environment-agnostic
