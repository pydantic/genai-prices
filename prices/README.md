# Pricing data for `genai-prices`

## DO NOT MOVE `data.json` OR `data_slim.json`!

Or associated `.schema.json` files.

These files are downloaded by packages to auto-update prices, so their URLs must not change.

## Contributing

We welcome contributions from the community and especially model/inference providers!

### Manual price updates

The simplest way to contribute is to edit the [`./providers`](./providers) YAML files to correct/update/extend models.

**Tip:** if you're using a modern IDE to edit the files, you should get warnings and auto-completion for the fields within the YAML files.

When you edit the prices of a model, remember to:

* add or update the `prices_checked` field on the model to the current date
* if relevant, add or update `price_comments` on the provider or model explaining the change and providing a link as a reference,
  if those fields don't make sense, you can also add a comment next to your change
* have `pre-commit` installed (generally you'll just need to run `make install` from the root directory),
  which will update the `data*.json` files when prices change. You can also run `make build` to update these files manually.

Please do not:

* edit any JSON file directly - they're all built with `make build` and are compact by design
* add verbose descriptions to providers or models, we only need enough detail to give the end user a rough idea of the model's capabilities
* try to change the schema of providers or models without creating an issue to discuss the changes first
* add new providers without creating an issue to discuss the changes first, adding models is fine

### Automatic price discrepancy detection

This project supports pulling prices from
[Helicone](https://github.com/Helicone/helicone/tree/main/packages/cost),
[Open Router](https://openrouter.ai/docs/api-reference/list-available-models),
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
