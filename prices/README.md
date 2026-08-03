# Pricing data for `genai-prices`

## DO NOT MOVE PUBLISHED DATA ARTIFACTS!

The legacy v1 artifacts remain directly under `prices/`. New contracts live under versioned directories such as
`prices/new_data/v2/`; later contracts should use a new `prices/new_data/v<version>/` directory rather than adding
version-suffixed files to the flat `prices/` directory.

These files are downloaded by packages to auto-update prices, so their URLs must not change.

**v1 is frozen.** `prices/data.json` and `prices/data_slim.json` are compatibility snapshots for clients released
before v2. No build step writes them, and they receive no provider, model or price updates. `prices/new_data/v2/`
is the live feed.

## Contributing

We welcome contributions from the community and especially model/inference providers!

### Manual price updates

The simplest way to contribute is to edit the [`./providers`](./providers) YAML files to correct/update/extend models.

**Tip:** if you're using a modern IDE to edit the files, you should get warnings and auto-completion for the fields within the YAML files.

When you edit the prices of a model, remember to:

- add or update the `prices_checked` field on the model to the current date
- if relevant, add or update `price_comments` on the provider or model explaining the change and providing a link as a reference,
  if those fields don't make sense, you can also add a comment next to your change
- have `pre-commit` installed (generally you'll just need to run `make install` from the root directory),
  which will update the v2 and package data when prices change. You can also run `make build` to update these files manually.

### Prices that depend on the request

Models priced differently depending on how the request was served carry `price_variants` alongside `prices`.
Each variant names the pricing context it applies to and the prices that replace the standard ones:

```yaml
prices:
  input_mtok: 5
  output_mtok: 25
  web_searches_kcount: 10
price_variants:
  - when: { service_tier: batch }
    prices:
      input_mtok: 2.5
      output_mtok: 12.5
```

`service_tier` covers the mutually exclusive rate cards - `batch` for the provider's batch API, `flex` and
`priority` for the synchronous tiers - and is the name Anthropic and Groq use in their own usage payloads.
`speed` (Anthropic's fast mode) and `inference_geo` (data residency) are also available.

A variant's prices override `prices` key by key, so only list the keys whose rate actually changes. Anything
omitted keeps its standard rate - above, web searches are not discounted in batch, so they are left out rather
than repeated. When `prices` carries a dated price history, each variant has to repeat those dates, since both
are resolved by the same constraints; `make build` rejects a variant that skips one.

Only add rates the provider publishes, and only for models it will actually serve that way: discounts are not
uniform (xAI's batch discount is 20%, Google bills batch cache hits at the standard cache rate on most models,
Groq's batch rate ignores caching entirely), and a model with no variant for a context is simply charged its
standard rates.

Please do not:

- edit generated JSON files directly — edit the provider YAML and use `make build` instead
- modify the frozen v1 compatibility artifacts at all
- add a unit to `units.yml` to make a model fit — that widens the published v2 schema and is a v3 change,
  see the header comment in that file
- add verbose descriptions to providers or models, we only need enough detail to give the end user a rough idea of the model's capabilities
- try to change the schema of providers or models without creating an issue to discuss the changes first
- add new providers without creating an issue to discuss the changes first, adding models is fine

### Automatic price discrepancy detection

This project supports pulling prices from
[Helicone](https://github.com/Helicone/helicone/tree/main/packages/cost),
[Open Router](https://openrouter.ai/docs/api/api-reference/models/get-models),
[LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) and
Simon Willison's [llm-prices](https://github.com/simonw/llm-prices/pull/7)

And injecting price discrepancy information into the YAML files.

To inject price discrepancies, run (from the repo root):

```bash
make get-update-price-discrepancies
```

Which will download the latest prices from those sources and inject price discrepancies into the YAML files, by default
price discrepancies are only injected into models where `prices_checked` is unset or older than 30 days.

You then need to go through files and resolve each discrepancy manually.
