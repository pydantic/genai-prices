# @pydantic/genai-prices

JavaScript package and command-line tool for calculating LLM API prices.

## Basic usage

### `calcPrice`

The package exports a function for price calculation that, by default, uses the bundled price data.

```ts
import { calcPrice } from '@pydantic/genai-prices'

const usage = { input_tokens: 1000, output_tokens: 100 }

const result = calcPrice(usage, 'gpt-3.5-turbo', { providerId: 'openai' })

if (result) {
  console.log(
    `$${result.total_price} (input: $${result.input_price}, output: $${result.output_price})`,
    result.provider.name,
    result.model.name
  )
} else {
  console.log('No price found for this model/provider combination')
}
```

### Request pricing context

```ts
import { calcPrice } from '@pydantic/genai-prices'

const price = calcPrice({ input_tokens: 1_000_000, output_tokens: 1_000_000 }, 'o3', {
  providerId: 'openai',
  timestamp: new Date('2026-10-12T00:00:00Z'),
  priceContext: { service_tier: 'flex' },
})
if (!price || price.total_price !== 5) {
  throw new Error('Expected the verified o3 flex price')
}
```

You pass `priceContext` explicitly to select request-specific prices. Its keys and values are strings.
Use the `service_tier` reported in OpenAI's response. A priority request can be downgraded and report `default`.
`auto` is a request setting and does not identify the rate you were charged. Extraction does not infer a context.
Tier variants are specific to their provider. If model lookup falls back to another provider, you receive the
standard-price estimate; the fallback provider's tier rates are not applied.

OpenAI variants cover `flex`, `priority`, and `fast` where the published rate table supports them.
`default` selects standard prices on these models. Omit the context for ordinary standard pricing.

If a context matches no variant, you receive the standard-price estimate.
This includes unsupported models, unknown tiers, misspelled keys, and dates without verified tier rates.
The bundled tier rates are verified from October 12, 2026; earlier tier history is not modeled.

### Batch API

```ts
import { calcPrice } from '@pydantic/genai-prices'

const price = calcPrice({ input_tokens: 1_000_000, output_tokens: 1_000_000 }, 'o3', {
  providerId: 'openai',
  timestamp: new Date('2026-10-14T00:00:00Z'),
  priceContext: { processing: 'batch' },
})
if (!price || price.total_price !== 5) {
  throw new Error('Expected the verified o3 batch price')
}
```

You pass `{ processing: 'batch' }` for usage from a provider's batch API. Most providers do not mark batch results in
the response, so you set it yourself. Batch is a separate key from `service_tier` because it is a way of submitting
requests, not a tier: OpenAI batch results report `service_tier: "default"`.

Batch rates are bundled for Anthropic, OpenAI, Google, Mistral, Groq and xAI, verified from October 14, 2026.
A model the provider does not serve in batch returns the standard-price estimate.

### Perplexity web search

For `perplexity/sonar`, pass the search type used in the Perplexity request:

```ts
import { calcPrice } from '@pydantic/genai-prices'

const price = calcPrice({ web_searches: 2 }, 'perplexity/sonar', {
  providerId: 'perplexity',
  priceContext: { search_type: 'fast' },
})
if (!price) {
  throw new Error('No price found for perplexity/sonar')
}
console.log(price.total_price) // 0.002
```

The response reports the search count but not the search type, so extraction cannot select the rate automatically.
Pass `search_type: fast` even when a Perplexity preset selects Fast Search. Omitting the context or passing
`search_type: web` uses the standard estimate of $2.50 per thousand searches. The fast rate is $1 per thousand.
The search type selects the rate independently of the request date. Token charges are calculated separately.
See [Perplexity's web-search documentation](https://docs.perplexity.ai/docs/agent-api/tools/web-search).

### Cached input tokens

```ts
import { calcPrice } from '@pydantic/genai-prices'

const result = calcPrice(
  {
    input_tokens: 4740,
    cache_read_tokens: 0,
    cache_write_tokens: 4735,
    output_tokens: 255,
  },
  'claude-sonnet-4-20250514',
  { providerId: 'anthropic' }
)

if (!result) {
  throw new Error('No price found for claude-sonnet-4-20250514')
}

console.log(result.total_price)
```

`input_tokens` is the total number of input tokens. It includes uncached tokens, cache-read tokens, and cache-write
tokens. You also report `cache_read_tokens` and `cache_write_tokens` so that `calcPrice` can apply their separate rates.

Do not pass only the uncached count as `input_tokens`. Cache tokens are partitions of the total, so their combined count
cannot exceed `input_tokens`.

### Fractional usage values

Every reportable usage unit accepts finite non-negative numbers, including fractions. This is useful for duration units
such as seconds:

```ts
const usage = { audio_seconds: 0.25 }
JSON.stringify(usage)
```

Usage remains a plain JSON-serializable object. JavaScript uses ordinary `number` arithmetic, so compare fractional
results with an appropriate numerical tolerance. The package guards decomposition against insignificant floating-point
residuals, but it cannot recover decimal precision that was already lost before a value was supplied.

For Groq's Whisper models, report the transcription duration as `audio_seconds` or `input_audio_seconds`. These models
apply Groq's documented 10-second minimum. A missing or zero duration costs zero.

### `updatePrices`

You can optionally use `updatePrices` to implement logic that can periodically update the data used by `calcPrice`.
See the `src/examples/browser` directory for an example that implements a local storage-backed auto-update and `src/examples/node-script.ts` for an example of a file-based asynchronous auto-update implementation.

`calcPrice` is a synchronous function that uses the currently available data - either the bundled one, or the last data fetched from the `updatePrices` setup. To force `calcPrice` to await potential in-progress data updates that can happen in `enableAutoUpdate`, await the `waitForUpdate()` return value before calling `calcPrice`

```ts
import { calcPrice, updatePrices } from '@pydantic/genai-prices'

enableAutoUpdate(/** auto-update logic */)

// ...

// this guarantees that the latest data is used
await waitForUpdate()
const result = calcPrice(usage, 'gpt-5', { providerId: 'openai' })

console.log(
  `$${result.total_price} (input: $${result.input_price}, output: $${result.output_price})`,
  result.provider.name,
  result.model.name
)
```

### Provider Matching

The library uses intelligent provider matching:

1. **Explicit provider**: Use `providerId` parameter or `provider:model` format
2. **Model-based matching**: Uses the provider's `model_match` logic (e.g., OpenAI matches models starting with "gpt-")
3. **Fallback**: Tries to match based on model name patterns

**Best practices:**

- Always specify `providerId` if you know it (e.g., `openai`, `google`, etc.) for best results
- Use `provider:model` format in CLI for explicit provider selection
- The async API with `--auto-update` provides the most up-to-date pricing

### Custom Pricing / New Models

If a model is not yet available in the bundled catalog, you can provide your own pricing definition. By passing a `provider` object in the options, the library will use your custom data instead of the internal catalog.

```ts
import { calcPrice, Provider } from '@pydantic/genai-prices'

const customProvider: Provider = {
  id: 'custom-provider',
  name: 'Custom Provider',
  api_pattern: '.*',
  models: [
    {
      id: 'my-new-model',
      match: { equals: 'my-new-model' },
      prices: {
        input_mtok: 2.5,
        output_mtok: 10.0,
      },
    },
  ],
}

const usage = { input_tokens: 1000, output_tokens: 100 }
const result = calcPrice(usage, 'my-new-model', { provider: customProvider })
```

**Required fields:**

- `Provider`: `id`, `name`, `api_pattern`, and `models` array
- `ModelInfo`: `id`, `match` (determines how the model ID is matched), and `prices`

**Pricing fields.** The full set is derived from
[`prices/units.yml`](https://github.com/pydantic/genai-prices/blob/main/prices/units.yml); the common
per-million-token ones are:

- `input_mtok` / `output_mtok`: Text token pricing
- `cache_read_mtok` / `cache_write_mtok`: Prompt caching pricing
- `input_audio_mtok` / `output_audio_mtok`: Audio token pricing

The key suffix tells you the unit, and **not every key is per million**: `_mtok` is per 1M tokens,
`_kcount` per 1,000 (e.g. `requests_kcount`, `web_searches_kcount`), `_mchars` per 1M characters,
`_hours` per 3,600 seconds, `_gpixels` per 1e9 pixels, `_kpages` per 1,000 pages.

Prices must also cover their ancestors: a model priced with `cache_write_1h_mtok` needs
`cache_write_mtok` as well, or pricing throws at runtime.

### Error Handling

When a model or provider is not found, the library returns `null`. This makes it easier to handle cases where pricing information might not be available.

```js
import { calcPrice } from '@pydantic/genai-prices'

const usage = { input_tokens: 1000, output_tokens: 100 }

// Returns null if model/provider not found
const result = calcPrice(usage, 'non-existent-model')
if (result === null) {
  console.log('No pricing information available for this model')
} else {
  console.log(`Total Price: $${result.total_price} (input: $${result.input_price}, output: $${result.output_price})`)
}

// Async version also returns null
const asyncResult = await calcPrice(usage, 'non-existent-model', { awaitAutoUpdate: true, providerId: 'unknown-provider' })
if (asyncResult === null) {
  console.log('No pricing information available for this model/provider combination')
} else {
  console.log(`Total Price: $${asyncResult.total_price} (input: $${asyncResult.input_price}, output: $${asyncResult.output_price})`)
}
```

## Troubleshooting

### Common Issues

- **No price found (returns null)**:
  - Make sure you specify the correct `providerId` (e.g., `openai`, `google`, `anthropic`)
  - Try using `provider:model` format in CLI
  - Use `--auto-update` flag to fetch latest data
  - Check that the model name is correct and supported by the provider

## CLI

The easiest way to run the latest version of the package as a CLI tool is through npx:

```bash
npx @pydantic/genai-prices@latest
```

For example:

```bash
npx @pydantic/genai-prices@latest calc gpt-4 --input-tokens 1000 --output-tokens 500
npx @pydantic/genai-prices@latest list
```

You can also install it globally and then use the `genai-prices` command:

```bash
npm i -g @pydantic/genai-prices
```

```bash
# Basic usage
genai-prices gpt-5 --input-tokens 1000 --output-tokens 100

# Specify provider explicitly
genai-prices openai:gpt-5 --input-tokens 1000 --output-tokens 100

# List available providers and models
genai-prices list
genai-prices list openai
```

In `provider:model` arguments, the first colon separates the provider from the model.
Any remaining colons are part of the model ID, for example in an OpenAI fine-tuned model:

```bash
genai-prices calc openai:ft:gpt-4o-2024-08-06:org:custom:id --input-tokens 1000 --output-tokens 100
```
