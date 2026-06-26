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

### Updating prices in the background

`update_prices_in_background()` periodically updates the price data by downloading it from GitHub.

Please note:

- this functionality is explicitly opt-in
- we download data directly from GitHub (`https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json`) so we don't and can't monitor requests or gather telemetry

At the time of writing, the `data.json` file downloaded is around 26KB when compressed, so is generally very
quick to download. By default the first fetch happens immediately in the background, then every hour after that.

```py
from genai_prices import update_prices_in_background

handle = update_prices_in_background()
...
handle.close()  # stop updating when you no longer need it
```

A single shared, process-wide updater backs this function, so it is safe to call from anywhere — including from
multiple libraries in the same process. The first call starts the updater; later calls reuse it and return
independent handles. The updater is stopped only when the **last** handle is closed, at which point prices revert
to the data bundled with the installed package. The handle is also a context manager (`with
update_prices_in_background() as handle: ...`).

**For libraries and integrations** (e.g. Logfire, Pydantic AI): call `update_prices_in_background()` with no
arguments, once, at startup. If several libraries do this, they share the one updater rather than spawning
duplicate threads, and each library's handle independently keeps it alive until closed. Leave configuration to
the application.

**For application authors** who need a custom URL or refresh interval: pass them, and call early in startup,
before the libraries initialize:

```py
update_prices_in_background(url='https://my-mirror.example/prices.json', update_interval=1800)
```

Configuration is **first-wins**: the first caller's `url`, `update_interval` and `request_timeout` apply for the
lifetime of the shared updater. A later caller passing different settings gets a handle on the already-running
updater and a warning logged on the `genai-prices` logger — its settings are ignored. Calling early ensures your
configuration is the one that takes effect.

`UpdatePricesHandle.close()` is idempotent and never raises; errors from the background updater are logged
instead. Closing the last handle stops the updater and reverts prices to the bundled data immediately. If a
fetch is in flight, the daemon thread is given a short grace period to exit and is otherwise abandoned with a
warning log: it exits once the fetch completes, and its result is discarded — a stopped updater can never
install prices afterwards. Other updater API calls are never blocked, and `calc_price` is always unaffected. A
handle represents exactly one claim on the updater — don't copy one, as closing the copy releases the original's
claim too.

`update_prices_in_background()` does not wait for the download. Until the first fetch completes, `calc_price`
keeps using the data bundled with the installed package, so prices for models released after that snapshot may be
missing for the first moments of the process. Once the fetch lands, every subsequent calculation uses the fresh
data — prices computed before then are not recalculated. If you need fresh prices before calculating (e.g. in a
short-lived script), call `wait_prices_updated_sync()` / `wait_prices_updated_async()` after acquiring the
handle — these never raise and return `False` if the update failed (the error is logged on the `genai-prices`
logger), so your calculations simply fall back to the bundled data.

You can wait for prices to be updated from anywhere with `wait_prices_updated_sync`:

```py
from genai_prices import wait_prices_updated_sync

wait_prices_updated_sync()
...
```

Or its async variant, `wait_prices_updated_async`.

#### Deprecated: the `UpdatePrices` class

The `UpdatePrices` class (`UpdatePrices().start()` / `.stop()` / `with UpdatePrices():`) is **deprecated** and
emits a `DeprecationWarning`. It now routes through the same shared updater described above and will be removed in
a future release — use `update_prices_in_background()` instead. Note the behaviour change: because there is now a
single shared updater, starting a second `UpdatePrices` no longer raises and no longer takes over an updater
another caller already started; configuration is first-wins.

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
