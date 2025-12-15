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

## Features

- Advanced logic for matching on model and provider IDs to maximise the chance of using the correct model
- Support for historic prices and prices changes, e.g. we have the prices for o3 before and after its price changed
- Support for variable daily prices, e.g. we support calculating deepseek prices even with off-peak pricing
- tiered pricing support for Gemini models where you pay a separate price for very large contexts
- support for [identifying price discrepancies](prices/README.md) from other sources
- Python package, CLI
- JavaScript/TypeScript package, CLI
- TODO: API and web UI

### Providers

The following providers are currently supported:

[comment]: <> (providers-start)

- [Anthropic](prices/providers/anthropic.yml) - 16 models
- [Avian](prices/providers/avian.yml) - 4 models
- [AWS Bedrock](prices/providers/aws.yml) - 45 models
- [Microsoft Azure](prices/providers/azure.yml) - 50 models
- [Cerebras](prices/providers/cerebras.yml) - 5 models
- [Cohere](prices/providers/cohere.yml) - 6 models
- [Deepseek](prices/providers/deepseek.yml) - 2 models
- [Fireworks](prices/providers/fireworks.yml) - 7 models
- [Google](prices/providers/google.yml) - 26 models
- [Groq](prices/providers/groq.yml) - 29 models
- [HuggingFace (cerebras)](prices/providers/huggingface_cerebras.yml) - 5 models
- [HuggingFace (fireworks-ai)](prices/providers/huggingface_fireworks-ai.yml) - 10 models
- [HuggingFace (groq)](prices/providers/huggingface_groq.yml) - 4 models
- [HuggingFace (hyperbolic)](prices/providers/huggingface_hyperbolic.yml) - 18 models
- [HuggingFace (nebius)](prices/providers/huggingface_nebius.yml) - 27 models
- [HuggingFace (novita)](prices/providers/huggingface_novita.yml) - 52 models
- [HuggingFace (nscale)](prices/providers/huggingface_nscale.yml) - 20 models
- [HuggingFace (publicai)](prices/providers/huggingface_publicai.yml) - 6 models
- [HuggingFace (sambanova)](prices/providers/huggingface_sambanova.yml) - 7 models
- [HuggingFace (together)](prices/providers/huggingface_together.yml) - 21 models
- [Mistral](prices/providers/mistral.yml) - 23 models
- [Novita](prices/providers/novita.yml) - 34 models
- [OpenAI](prices/providers/openai.yml) - 63 models
- [OpenRouter](prices/providers/openrouter.yml) - 575 models
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
- [Open Router](https://openrouter.ai/docs/api/api-reference/models/get-models)
- [LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json)
- Simon Willison's [llm-prices](https://github.com/simonw/llm-prices/pull/7)

While none of these sources had exactly what we needed (hence creating this project), they (especially helicone) were used to populate some of the initial price database, and we continue to pull price updates from them.

Thanks to all those projects!
