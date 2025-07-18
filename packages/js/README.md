# genai-prices (JS/TS)

A JavaScript/TypeScript library for calculating prices for calling LLM inference APIs, using the [genai-prices](https://github.com/pydantic/genai-prices) data.

## Features

- Loads model/provider pricing from JSON (local or remote)
- Advanced logic for matching model IDs
- Supports historic, tiered, and variable pricing
- Opt-in auto-update from GitHub
- CLI for listing models/providers and calculating prices
- **Sync and Async API**: Use local data or fetch latest from GitHub
- **Outdated data warning**: Warns if your local data is more than 1 day old

## Installation

```sh
npm install genai-prices
# or
yarn add genai-prices
```

## CLI Usage

### List all providers and models

```sh
node dist/cli.js list --auto-update
```

### List models for a specific provider

```sh
node dist/cli.js list openai --auto-update
```

### Calculate price for a model

```sh
node dist/cli.js calc --input-tokens 1000 --output-tokens 100 openai:gpt-3.5-turbo --auto-update
```

### Calculate price for a model with a timestamp (historic pricing)

```sh
node dist/cli.js calc --input-tokens 1000 --output-tokens 100 openai:gpt-4o --timestamp 2024-01-01T12:00:00Z --auto-update
```

### Show CLI help

```sh
node dist/cli.js --help
```

### Show CLI version

```sh
node dist/cli.js --version
```

## API Usage (TypeScript/Node.js)

### Synchronous API (local data only)

```ts
import { calcPriceSync } from 'genai-prices';
const usage = { inputTokens: 1000, outputTokens: 100 };
const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' });
console.log(result.price);
```

### Asynchronous API (fetches latest data, then caches)

```ts
import { calcPriceAsync, enableAutoUpdate } from 'genai-prices';
enableAutoUpdate(); // Always get the latest prices from GitHub
const usage = { inputTokens: 1000, outputTokens: 100 };
const result = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' });
console.log(result.price);
```

- **Note:** The async API fetches the latest data on first call, then uses cached data for subsequent calls (always returns a Promise).
- **Note:** The sync API always uses local data and will throw if the local data file is missing.
- **Outdated data warning:** If your local data is more than 1 day old, a warning will be printed. Use `make build` or `--auto-update` to update.

## License

MIT
