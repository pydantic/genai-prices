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

To use the CLI with Rich output/help, install the optional CLI dependencies:

```bash
uv add "genai-prices[cli]"
```

(or `pip install "genai-prices[cli]"`)

## Warning: these prices will not be 100% accurate

See [the project README](https://github.com/pydantic/genai-prices?tab=readme-ov-file#warning) for more information.

## Usage

### `calc_price`

```python
from genai_prices import Usage, calc_price

price_data = calc_price(
    Usage(input_tokens=1000, output_tokens=100),
    model_ref='gpt-4o',
    provider_id='openai',
)
print(f"Total Price: ${price_data.total_price} (input: ${price_data.input_price}, output: ${price_data.output_price})")
```

### `extract_usage`

`extract_usage` can be used to extract usage data and the `model_ref` from response data,
which in turn can be used to calculate prices:

```py
from genai_prices import extract_usage

response_data = {
    'model': 'claude-sonnet-4-20250514',
    'usage': {
        'input_tokens': 504,
        'cache_creation_input_tokens': 123,
        'cache_read_input_tokens': 0,
        'output_tokens': 97,
    },
}
extracted_usage = extract_usage(response_data, provider_id='anthropic')
price = extracted_usage.calc_price()
print(price.total_price)
```

or with OpenAI where there are two API flavors:

```py
from genai_prices import extract_usage

response_data = {
    'model': 'gpt-5',
    'usage': {'prompt_tokens': 100, 'completion_tokens': 200},
}
extracted_usage = extract_usage(response_data, provider_id='openai', api_flavor='chat')
price = extracted_usage.calc_price()
print(price.total_price)
```

### `UpdatePrices`

`UpdatePrices` can be used to periodically update the price data by downloading it from GitHub

Please note:

- this functionality is explicitly opt-in
- we download data directly from GitHub (`https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json`) so we don't and can't monitor requests or gather telemetry

At the time of writing, the `data.json` file
downloaded by `UpdatePrices` is around 26KB when compressed, so is generally very quick to download.

By default `UpdatePrices` downloads price data immediately after it's started in the background, then every hour after that.

Usage with `UpdatePrices` as as context manager:

```py
from genai_prices import UpdatePrices, Usage, calc_price

with UpdatePrices() as update_prices:
    update_prices.wait()  # optionally wait for prices to have updated
    p = calc_price(Usage(input_tokens=123, output_tokens=456), 'gpt-5')
    print(p)
```

Usage with `UpdatePrices` as a simple class:

```py
from genai_prices import UpdatePrices, Usage, calc_price

update_prices = UpdatePrices()
update_prices.start(wait=True)  # start updating prices, optionally wait for prices to have updated
p = calc_price(Usage(input_tokens=123, output_tokens=456), 'gpt-5')
print(p)
update_prices.stop()  # stop updating prices
```

Only one `UpdatePrices` instance can be running at a time.

For libraries and integrations that want to opt into updating prices without creating duplicate background
threads, use `update_prices_in_background()`:

```py
from genai_prices import update_prices_in_background

update_prices_handle = update_prices_in_background()
...
update_prices_handle.close()
```

The first call starts a shared process-wide updater with default settings (hourly refresh from the default URL —
the shared updater is not configurable; if you need a custom URL or interval, use `UpdatePrices` directly). Later
calls reuse the same updater and return independent handles. The updater is stopped when the last handle is
closed, at which point prices revert to the data bundled with the installed package.

A manually started `UpdatePrices` always takes precedence over the shared updater, regardless of which started
first:

- If an `UpdatePrices` instance has already been started manually, `update_prices_in_background()` does not start
  a second updater and returns a handle that does nothing on close: prices are already being kept up to date, and
  the manual updater's lifetime stays with whoever started it.
- If `UpdatePrices.start()` is called while the shared updater is running, the shared updater is stopped and the
  manual instance takes over; existing handles become inert. Prices briefly revert to the bundled data until the
  manual updater's first fetch completes — pass `wait` to `start()` to block until then.

Either way, an inert handle stays inert: if the manual updater is later stopped, background updates stop with
it — call `update_prices_in_background()` again to start a new shared updater. Both precedence cases are logged
at `INFO` level on the `genai-prices` logger, which is the place to look if background updates ever stop
unexpectedly.

`UpdatePricesHandle.close()` is idempotent and never raises; errors from the background updater are logged
instead. Closing the last handle stops the updater and waits for its thread to exit, so if a fetch is in flight,
`close()` (and `UpdatePrices.start()` when taking over) can block for roughly the request timeout (typically
10–15 seconds with the default settings, since httpx timeouts are per-operation rather than a total deadline).
Other updater lifecycle calls (`update_prices_in_background()`, `wait_prices_updated_sync()`) contend
on the same internal lock and can block for the same duration in that window; `calc_price` never takes that lock
and is unaffected. A handle represents exactly one claim on the updater — don't copy one, as closing the copy
releases the original's claim too.

`update_prices_in_background()` does not wait for the download. Until the first fetch completes, `calc_price`
keeps using the data bundled with the installed package, so prices for models released after that snapshot may be
missing for the first moments of the process. Once the fetch lands, every subsequent calculation uses the fresh
data — prices computed before then are not recalculated. If you need fresh prices before calculating (e.g. in a
short-lived script), call `wait_prices_updated_sync()` / `wait_prices_updated_async()` after acquiring the
handle — these never raise and return `False` if the update failed (the error is logged on the `genai-prices`
logger), so your calculations simply fall back to the bundled data.

To disable background updates entirely (e.g. in air-gapped environments, or when a library enables them on your
behalf), set the `GENAI_PRICES_DISABLE_AUTO_UPDATE` environment variable to any non-empty value:
`update_prices_in_background()` then returns a do-nothing handle and makes no network requests. This does not
affect manually created `UpdatePrices` instances.

If you'd like to wait for prices to be updated without access to the `UpdatePrices` instance, you can use the `wait_prices_updated_sync` function:

```py
from genai_prices import wait_prices_updated_sync

wait_prices_updated_sync()
...
```

Or it's async variant, `wait_prices_updated_async`.

### CLI Usage

Run the CLI with:

```bash
uvx genai-prices --help
```

Or, if installed locally, make sure CLI extras are present:

```bash
pip install "genai-prices[cli]"
genai-prices --help
```

If local CLI extras are not installed, the command will print an install hint for `genai-prices[cli]`.

To list providers and models, run:

```bash
uvx genai-prices list
```

To calculate the price of models, run for example:

```bash
uvx genai-prices calc --input-tokens 100000 --output-tokens 3000 o1 o3 claude-opus-4
```

CLI output notes:

- Rich output is the default.
- Use `--plain` (`-p`) for legacy/plain output.
- Use `--no-color` to keep rich formatting without colors.
- Use `-T` / `--table` for wide table output.

## Further Documentation

We do not yet build API documentation for this package, but the source code is relatively simple and well documented.

If you need further information on the API, we encourage you to read the source code.
