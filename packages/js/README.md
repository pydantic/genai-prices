# genai-prices (JS/TS)

A JavaScript/TypeScript library for calculating prices for calling LLM inference APIs, using the [genai-prices](https://github.com/pydantic/genai-prices) data.

## Features

- Loads model/provider pricing from JSON (local or remote)
- Advanced logic for matching model IDs
- Supports historic, tiered, and variable pricing
- Opt-in auto-update from GitHub
- **Sync API (Node.js only)**: Always reads from local prices/data.json
- **Async API (universal)**: Use in Node, browser, or cloud with storage callbacks
- **Outdated data warning**: Warns if your local data is more than 1 day old
- **Multi-model CLI support**: Calculate prices for multiple models in one command
- **Async prefetch**: Pre-warm the async cache at startup for fast first call
- **Background refresh**: Async cache is refreshed in the background if older than 30 minutes

## Installation

```sh
npm install @pydantic/genai-prices
# or
yarn add @pydantic/genai-prices
```

## API Usage

### Synchronous API (Node.js only, always reads from local prices/data.json)

```ts
import { calcPriceSync } from '@pydantic/genai-prices'
const usage = { inputTokens: 1000, outputTokens: 100 }
const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
console.log(result.price)
// Note: This only works in Node.js and always uses the local file prices/data.json
```

### Asynchronous API (universal, works in Node, browser, or cloud)

```ts
import { calcPriceAsync, enableAutoUpdate, prefetchAsync } from '@pydantic/genai-prices'
// In-memory (default, works everywhere)
enableAutoUpdate() // No storage option = in-memory
prefetchAsync() // (Optional) Pre-warm the async cache at startup
const usage = { inputTokens: 1000, outputTokens: 100 }
const result = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
console.log(result.price)
```

### Asynchronous API (browser, using localStorage)

```ts
import { calcPriceAsync, enableAutoUpdate } from '@pydantic/genai-prices'
const browserStorage = {
  get: async () => window.localStorage.getItem('genai-prices-data'),
  set: async (data) => {
    window.localStorage.setItem('genai-prices-data', data)
    window.localStorage.setItem('genai-prices-data:ts', Date.now().toString())
  },
  getLastModified: async () => {
    const ts = window.localStorage.getItem('genai-prices-data:ts')
    return ts ? Number(ts) : null
  },
}
enableAutoUpdate({ storage: browserStorage })
const usage = { inputTokens: 1000, outputTokens: 100 }
const result = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
console.log(result.price)
```

- **Note:** The sync API is Node.js only and always uses the local file prices/data.json.
- **Note:** The async API is universal and works in any environment with storage callbacks.
- **Note:** The async API fetches the latest data on first call, then uses cached data for subsequent calls (always returns a Promise).
- **Note:** If the async cache is older than 30 minutes, a background refresh is started, but the old data is served until the new data is ready.
- **Note:** Call `prefetchAsync()` at startup to pre-warm the async cache for fast first call (matches Python's prefetch_async).
- **Note:** You can provide your own custom storage backend by passing `get`, `set`, and `getLastModified` callbacks.
- **Outdated data warning:** If your local data is more than 1 day old, a warning will be printed. Use `make build` or `--auto-update` to update.

## CLI Usage

You can use the CLI either locally (via `node dist/cli.js ...`) or globally (after installing with `npm i -g @pydantic/genai-prices`).

### Global CLI Usage

Install globally:

```sh
npm install -g @pydantic/genai-prices
```

Then use the CLI directly:

```sh
@pydantic/genai-prices list --auto-update
@pydantic/genai-prices calc --input-tokens 1000 --output-tokens 100 openai:gpt-3.5-turbo --auto-update
```

### Local CLI Usage (from project root)

```sh
node dist/cli.js list --auto-update
node dist/cli.js calc --input-tokens 1000 --output-tokens 100 openai:gpt-3.5-turbo --auto-update
```

### Calculate prices for multiple models in one command

```sh
@pydantic/genai-prices calc --input-tokens 100000 --output-tokens 3000 o1 o3 claude-opus-4 --auto-update
```

- Each model will be processed in turn. Errors for individual models are reported but do not stop the batch.

### Calculate price for a model with a timestamp (historic pricing)

```sh
@pydantic/genai-prices calc --input-tokens 1000 --output-tokens 100 openai:gpt-4o --timestamp 2024-01-01T12:00:00Z --auto-update
```

### Show CLI help

```sh
@pydantic/genai-prices --help
```

### Show CLI version

```sh
@pydantic/genai-prices --version
```

## License

MIT
