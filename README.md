<div align="center">
  <h1>GenAI Prices</h1>
</div>
<div align="center">
  <a href="https://github.com/pydantic/genai-prices/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://github.com/pydantic/genai-prices/actions/workflows/ci.yml/badge.svg?event=push" alt="CI"></a>
  <a href="https://coverage-badge.samuelcolvin.workers.dev/redirect/pydantic/genai-prices"><img src="https://coverage-badge.samuelcolvin.workers.dev/pydantic/genai-prices.svg" alt="Coverage"></a>
  <a href="https://pypi.python.org/pypi/genai-prices"><img src="https://img.shields.io/pypi/v/genai-prices.svg" alt="PyPI"></a>
  <a href="https://github.com/pydantic/genai-prices"><img src="https://img.shields.io/pypi/pyversions/genai-prices.svg" alt="versions"></a>
  <a href="https://github.com/pydantic/genai-prices/blob/main/LICENSE"><img src="https://img.shields.io/github/license/pydantic/genai-prices.svg" alt="license"></a>
  <a href="https://logfire.pydantic.dev/docs/join-slack/"><img src="https://img.shields.io/badge/Slack-Join%20Slack-4A154B?logo=slack" alt="Join Slack" /></a>
</div>
<br/>
<div align="center">
  Calculate prices for calling LLM inference APIs.
</div>
<br/>

## 🛠️ Work in Progress

This package is a work in progress:

- [x] price data YAML
- [x] JSON file with all prices
- [x] Python library with functionality to calculate prices, including opt-in support for phoning home to get latest prices
- [x] JS/TS library with functionality to calculate prices, including opt-in support for phoning home to get latest prices
- [x] Beta release workflow with changesets for versioning and publishing
- [ ] API (and I guess UI) for calculating latest prices

## Features

- Advanced logic for matching on model and provider IDs to maximise the chance of using the correct model
- Support for historic prices and prices changes, e.g. we have the prices for o3 before and after it's price changed
- Support for variable daily prices, e.g. we support calculating deepseek prices even with off-peak pricing
- tiered pricing support for Gemini models where you pay a separate price for very large contexts
- support for [identifying price discrepancies](prices/README.md) from other sources
- Python package, CLI
- JavaScript/TypeScript package, CLI
- TODO: API and web UI

### Provider and Model Matching

The library automatically handles provider aliases and model name variations through YAML-based configuration. This allows you to use various provider identifiers and model names while the library maps them to the correct providers and models.

**Provider Aliases:**

Provider aliases are defined in the YAML configuration files and support the same matching logic as models:

- **Google**: `google`, `gemini`, `google-gla`, `google-vertex`, `google-ai`
- **Meta**: `meta`, `meta-llama`, `llama`
- **Mistral**: `mistral`, `mistralai`
- **Anthropic**: `anthropic`, `claude`
- **OpenAI**: `openai`, `gpt`

**Model Normalization:**

The library also normalizes model names for consistency:

- **Anthropic Claude Opus 4**: Any model starting with `claude-opus-4` is normalized to `claude-opus-4-20250514`
- **OpenAI GPT-3.5**: Any model starting with `gpt-3.5-turbo` is normalized to `gpt-3.5-turbo`

This allows you to use various provider and model names without worrying about exact matching:

```python
# Python
from genai_prices import calc_price_sync

# These all work automatically:
result = calc_price_sync(usage, 'gemini-2.5-pro', provider_id='google-vertex')
result = calc_price_sync(usage, 'gemini-2.5-pro', provider_id='google-gla')
result = calc_price_sync(usage, 'claude-opus-4-something', provider_id='anthropic')
```

```typescript
// JavaScript/TypeScript
import { calcPriceSync } from '@pydantic/genai-prices'

// These all work automatically:
const result1 = calcPriceSync(usage, 'gemini-2.5-pro', { providerId: 'google-vertex' })
const result2 = calcPriceSync(usage, 'gemini-2.5-pro', { providerId: 'google-gla' })
const result3 = calcPriceSync(usage, 'claude-opus-4-something', { providerId: 'anthropic' })
```

### Providers

The following providers are currently supported:

[comment]: <> (providers-start)

- [Anthropic](prices/providers/anthropic.yml) - 1 models
- [Avian](prices/providers/avian.yml) - 4 models
- [AWS Bedrock](prices/providers/aws.yml) - 4 models
- [Microsoft Azure](prices/providers/azure.yml) - 47 models
- [Cohere](prices/providers/cohere.yml) - 5 models
- [Deepseek](prices/providers/deepseek.yml) - 2 models
- [Fireworks](prices/providers/fireworks.yml) - 7 models
- [Google](prices/providers/google.yml) - 31 models
- [Groq](prices/providers/groq.yml) - 8 models
- [Mistral](prices/providers/mistral.yml) - 28 models
- [Novita](prices/providers/novita.yml) - 34 models
- [OpenAI](prices/providers/openai.yml) - 41 models
- [OpenRouter](prices/providers/openrouter.yml) - 548 models
- [Perplexity](prices/providers/perplexity.yml) - 8 models
- [Together AI](prices/providers/together.yml) - 72 models
- [X AI](prices/providers/x_ai.yml) - 7 models

[comment]: <> (providers-end)

## Usage

### Python Package & CLI

See the [Python README](packages/python/README.md) for instructions on how to install and use the Python package and CLI.

### JavaScript/TypeScript Package

See the [JS/TS README](packages/js/README.md) for instructions on how to install and use the JavaScript/TypeScript package and CLI.

### Download data

Price data is available in the following files:

- [`prices/data.json`](prices/data.json) - JSON file with all prices
- [`prices/data.schema.json`](prices/data.schema.json) - JSON Schema for `prices/data.json`
- [`prices/data_slim.json`](prices/data_slim.json) - JSON file long fields like descriptions removed and free models removed
- [`prices/data_slim.schema.json`](prices/data_slim.schema.json) - JSON Schema for `prices/data_slim.json`

Feel free to download these files and use them as you wish. We would be grateful if you would reference this
project wherever you use it and [contribute](#contributing) back to the project if you find any errors.

### Release Workflow

This project uses [changesets](https://github.com/changesets/changesets) for versioning and publishing js package:

- **Stable releases**: Automatically published when PRs are merged to main (if changesets are present)
- **Beta releases**: Use the GitHub Actions workflow "Beta Release" to:
  - Enter beta mode: Creates a PR to enable beta releases
  - Version packages: Creates a PR with new beta versions
  - Exit beta mode: Creates a PR to disable beta releases and prepare for stable release

### API

Coming soon...

<h2 id="warning">⚠️ Warning: these prices will not be 100% accurate</h2>

This project is a best effort from Pydantic and the community to provide an indicative
estimate of the price you might pay for calling an LLM.

The price data cannot be exactly correct because model providers do not provide exact price information for their APIs
in a format which can be reliably processed.

If you get a bill you weren't expecting, don't blame us!

If you're a lawyer, please read the [LICENSE](https://github.com/pydantic/genai-prices/blob/main/LICENSE) under which this project is developed, hosted and distributed.

If you're a developer, please [contribute](#contributing) to fix any missing or incorrect prices you find.

## Contributing

We welcome contributions from the community and especially model/inference providers!

**If you're a model provider:** it would be amazing if you would serve a JSON file or API endpoint with
pricing information which we could pull from. You would be the first AFAIK, and I think it would
dramatically improve the experience for developers using your API!

Otherwise, to contribute:

- See [`prices/README.md`](prices) for instructions on how to contribute to the price data.
- Feel free to submit pull requests or issues about the Python and JS packages.
- If you need a library for another language, please create an issue, we'd be happy to discuss building it, hosting it here,
  or helping you maintain it elsewhere.

## Thanks

This project would not be possible without the following existing data sources:

- [Helicone](https://github.com/Helicone/helicone/tree/main/packages/cost)
- [Open Router](https://openrouter.ai/docs/api-reference/list-available-models)
- [LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json)
- Simon Willison's [llm-prices](https://github.com/simonw/llm-prices/pull/7)

While none of these sources had exactly what we needed (hence creating this project), they (especially helicone) were used to populate some of the initial price database, and we continue to pull price updates from them.

Thanks to all those projects!
