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

`UpdatePrices` periodically updates the price data by downloading it from GitHub.

Please note:

- this functionality is explicitly opt-in
- we download data directly from GitHub (`https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json`) so we don't and can't monitor requests or gather telemetry

At the time of writing, the `data.json` file downloaded is around 26KB when compressed, so is generally very
quick to download. By default the first fetch happens immediately in the background, then every hour after that.

Usage as a context manager:

```py
from genai_prices import UpdatePrices, Usage, calc_price

with UpdatePrices() as update_prices:
    update_prices.wait()  # optionally wait for prices to have updated
    p = calc_price(Usage(input_tokens=123, output_tokens=456), 'gpt-5')
    print(p)
```

Or by calling `start()` / `stop()` yourself:

```py
from genai_prices import UpdatePrices, Usage, calc_price

update_prices = UpdatePrices()
update_prices.start(wait=True)  # optionally wait for the first update
p = calc_price(Usage(input_tokens=123, output_tokens=456), 'gpt-5')
print(p)
update_prices.stop()
```

A single shared, process-wide updater backs every `UpdatePrices` instance. Starting an instance acquires shared
ownership rather than creating a private thread: the first `start()` launches the updater, compatible later
instances join it, and the last `stop()` shuts it down and restores the data bundled with the installed package.
This lets libraries such as Logfire and Pydantic AI opt in independently without creating duplicate threads.

The active updater's `url`, `update_interval`, and `request_timeout` must match. A second instance with different
settings raises `RuntimeError` instead of silently ignoring its configuration. The first owner also supplies the
`fetch()` implementation, so subclasses continue to work while later instances are ownership claims only.
Applications that need custom behavior should start their updater before integrations initialize and retain it
until shutdown.

The last `stop()` keeps the existing shutdown behavior: it waits for an in-flight fetch to finish, then restores
the bundled snapshot. Background failures are raised once per owner by `wait()` or `stop()`; a process-wide wait
observes the failure for every current owner. `calc_price()` does not acquire either updater lock.

As with other background threads, start the updater only after calling `os.fork()`; inheriting a running updater
in a child process is unsupported.

`start()` does not wait for the download (unless you pass `wait`). Until the first fetch completes, `calc_price`
keeps using the data bundled with the installed package, so prices for models released after that snapshot may be
missing for the first moments of the process. Once the fetch lands, every subsequent calculation uses the fresh
data — prices computed before then are not recalculated. If you need fresh prices before calculating (e.g. in a
short-lived script), pass `wait` to `start()`, or call `wait_prices_updated_sync()` /
`wait_prices_updated_async()`. Fetch failures are raised by these methods, matching `UpdatePrices.wait()`.

You can wait for prices to be updated from anywhere — without access to the `UpdatePrices` instance — with
`wait_prices_updated_sync`:

```py
from genai_prices import wait_prices_updated_sync

wait_prices_updated_sync()
...
```

Or its async variant, `wait_prices_updated_async`.

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
