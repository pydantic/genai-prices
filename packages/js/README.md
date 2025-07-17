# genai-prices (JS/TS)

A JavaScript/TypeScript library for calculating prices for calling LLM inference APIs, using the [genai-prices](https://github.com/pydantic/genai-prices) data.

## Features

- Loads model/provider pricing from JSON (local or remote)
- Advanced logic for matching model IDs
- Supports historic, tiered, and variable pricing
- Opt-in auto-update from GitHub
- CLI for listing models/providers and calculating prices

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

```ts
import { calcPrice, enableAutoUpdate, Usage } from 'genai-prices';

// Enable auto-update to always use the latest data from GitHub
enableAutoUpdate();

const usage: Usage = { inputTokens: 1000, outputTokens: 100 };

const result = await calcPrice(usage, 'gpt-3.5-turbo', { providerId: 'openai' });
console.log(result.price); // e.g., 0.0012
console.log(result.provider.name); // 'OpenAI'
console.log(result.model.name); // 'gpt 3.5 turbo'
```

## Auto-Update

By default, the library uses bundled price data. To enable auto-update from GitHub:

```ts
import { enableAutoUpdate } from 'genai-prices';
enableAutoUpdate();
```

Or use the `--auto-update` flag in the CLI.
