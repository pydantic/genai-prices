# @pydantic/genai-prices

JavaScript package and command-line tool for calculating LLM API prices.

## Basic usage

### `calcPriceSync`

The package exports a synchronous function for price calculation that, by default, uses the bundled price data.

```ts
import { calcPriceSync } from '@pydantic/genai-prices'

const usage = { input_tokens: 1000, output_tokens: 100 }

// Sync (works everywhere, including browser)
const result = calcPriceSync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
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

You can optionally use `enableAutoUpdateForSyncCalc` to implement asynchronous auto-update logic for the data used by `calcPriceSync`.
When enabled, the function will use the most recently available data while updates occur in the background. See the `src/examples/browser` directory for an example that implements a local storage-backed auto-update.

### `calcPriceAsync`

If you want to ensure that the calculation always uses the latest provider data, you can use the asynchronous API `calcPriceAsync` and implement `enableAutoUpdateForAsyncCalc` to fetch a fresh snapshot.
Unlike the synchronous API, `calcPriceAsync` will await any data updates to complete before returning the result. See `src/examples/node-script.ts` for an example of a file-based asynchronous auto-update implementation.

```ts
import { calcPriceAsync } from '@pydantic/genai-prices'

const result = await calcPriceAsync(usage, 'gpt-3.5-turbo', { providerId: 'openai' })
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

When a model or provider is not found, the library returns `null`. This makes it easier to handle cases where pricing information might not be available.

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
genai-prices gpt-3.5-turbo --input-tokens 1000 --output-tokens 100

# Specify provider explicitly
genai-prices openai:gpt-3.5-turbo --input-tokens 1000 --output-tokens 100

# List available providers and models
genai-prices list
genai-prices list openai
```
