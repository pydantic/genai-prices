<div align="center">
  <h1>genai-prices</h1>
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
  Python package for <a href="https://github.com/pydantic/genai-prices">github.com/pydantic/genai-prices</a>.
</div>
<br/>

## Installation

```bash
uv add genai-prices
```

(or `pip install genai-prices` if you're old school)

## Warning: these prices will not be 100% accurate

See [the project README](https://github.com/pydantic/genai-prices?tab=readme-ov-file#warning) for more information.

## Usage

The library provides separated input and output pricing, giving you detailed breakdown of costs:

- `price_data.total_price` - Total cost for the request
- `price_data.input_price` - Cost for input/prompt tokens
- `price_data.output_price` - Cost for output/completion tokens

Since this library may need to make a network call to download prices, both sync and async veriants of `calc_price` are provided.

### Sync API Example

```python
from genai_prices import Usage, calc_price_sync

price_data = calc_price_sync(
    Usage(input_tokens=1000, output_tokens=100),
    model_ref='gpt-4o',
    provider_id='openai',
)
print(f"Total Price: ${price_data.total_price} (input: ${price_data.input_price}, output: ${price_data.output_price})")
```

### Async API Example

```python
import asyncio

from genai_prices import Usage, calc_price_async

async def main():
    price_data = await calc_price_async(
        Usage(input_tokens=1000, output_tokens=100),
        model_ref='gpt-4o',
        provider_id='openai',
    )
    print(f"Total Price: ${price_data.total_price} (input: ${price_data.input_price}, output: ${price_data.output_price})")

if __name__ == '__main__':
    asyncio.run(main())
```

### Auto Update

Both `calc_price_sync` and `calc_price_async` can be configured to auto-update by passing `auto_update=True` as an argument.
This will cause the library to periodically check for updates to the price data.

Please note:

- this functionality is explicitly opt-in
- we download data directly from GitHub (`https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json`) so we don't and can't monitor requests or gather telemetry

You may also pass a custom source to `auto_update` to customize auto-update behavior.

At the time of writing, the `data.json` file
downloaded by auto-update is around 26KB when compressed, so is generally very quick to download.

None-the-less, the library tries hard to avoid making a network call when the user calls
`calc_price_sync` or `calc_price_async`:

- data is cached for one hour by default
- when the cached data is 30minutes old, the library will attempt to update the cache in the background
- You may pre-fetch data at program startup using `genai_prices.prefetch_async()` and `genai_prices.prefetch_sync()`,
  these are both sync methods which return immediately and update the cache in the background, the only difference is that
  `calc_price_async` will wait for the `prefetch_async` task to complete when it is first called, and `calc_price_sync` will wait for the `prefetch_sync` concurrent future to complete when it is first called.

### CLI Usage

Run the CLI with:

```bash
uvx genai-prices --help
```

To list providers and models, run:

```bash
uvx genai-prices list
```

To calculate the price of models, run for example:

```bash
uvx genai-prices calc --input-tokens 100000 --output-tokens 3000 o1 o3 claude-opus-4
```

## Further Documentation

We do not yet build API documentation for this package, but the source code is relatively simple and well documented.

If you need further information on the API, we encourage you to read the source code.
