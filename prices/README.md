# Pricing data for `genai-prices`

## DO NOT MOVE PUBLISHED DATA ARTIFACTS!

The legacy v1 artifacts remain directly under `prices/`. New contracts live under versioned directories such as
`prices/new_data/v2/`; later contracts should use a new `prices/new_data/v<version>/` directory rather than adding
version-suffixed files to the flat `prices/` directory.

These files are downloaded by packages to auto-update prices, so their URLs must not change.

**v1 is frozen.** `prices/data.json` and `prices/data_slim.json` are compatibility snapshots for clients released
before v2. No build step writes them, and they receive no provider, model or price updates. `prices/new_data/v2/`
is the live feed.

The v2 schema compatibility check permits the optional model `price_variants` field because older clients ignore it.
Every existing schema member, including the billable-unit vocabulary, remains protected. This exception does not allow
new units or changes to existing fields.

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

Please do not:

- edit generated JSON files directly — edit the provider YAML and use `make build` instead
- modify the frozen v1 compatibility artifacts at all
- add a unit to `units.yml` to make a model fit — that widens the published v2 schema and is a v3 change,
  see the header comment in that file
- add verbose descriptions to providers or models, we only need enough detail to give the end user a rough idea of the model's capabilities
- try to change the schema of providers or models without creating an issue to discuss the changes first
- add new providers without creating an issue to discuss the changes first, adding models is fine

### Request-specific prices

```yaml
id: example
name: Example
api_pattern: 'https://example\.com'
models:
  - id: example-model
    match: { equals: example-model }
    prices_checked: 2026-10-12
    prices:
      input_mtok: 2
      output_mtok: 8
      web_searches_kcount: 10
    price_variants:
      - when: { service_tier: flex }
        constraint: { start_date: 2026-10-12 }
        prices:
          input_mtok: 1
          output_mtok: 4
      - when: { service_tier: default }
        prices: {}
```

A price variant is a partial rate card selected by the caller's pricing context.
You keep the standard `prices` and add `price_variants` beside it.
This keeps existing v2 clients from applying a request-specific discount to every request.

Each `when` must contain at least one string key and string value. Every pair must match exactly, including case.
You can use the existing date and time constraints to limit a variant's validity.
For each price key, the first active matching variant that supplies a value wins.
Other keys retain their standard rates. An empty `prices` map acknowledges a standard-price context.
Null price values are omitted. A context with no matching variant gives a standard-price estimate.

Batch API rates use `when: { processing: batch }`, not `service_tier`. Batch is a way of submitting requests,
and providers disagree on what `service_tier` a batch result reports, so `service_tier` stays the value the response carries.

You list explicit per-unit rates because a discount may apply to tokens without applying to tools or storage.
Keep dated entries when rates change, and place newer variant entries before older ones.
Use a verified effective date. If you only know today's rates, state the historical coverage limit in `price_comments`
and constrain those rates to the verification date. Earlier requests then receive the standard-price estimate instead of an unverified tier rate.
When standard prices change, verify every variant independently. Its listed rates are absolute; omitted keys inherit standard prices for that date.
Prepend dated entries for changed tier rates, and cite a source for tiers whose rates stayed unchanged.
Test each affected context before and after the date boundary in all three packages.
Run `make build` after changing variants. The build validates each variant and their combined price keys with standard prices.

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
