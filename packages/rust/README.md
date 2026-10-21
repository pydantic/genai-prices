# GenAI Prices for Rust

Calculate the price of generative AI API calls, using the
[genai-prices](https://github.com/pydantic/genai-prices) database.

## Installation

```bash
cargo add genai-prices
```

## Calculate a price

```rust
use genai_prices::{PriceRequest, Usage, UsageKey};

let usage = Usage::from([(UsageKey::INPUT_TOKENS, 1_000.0), (UsageKey::OUTPUT_TOKENS, 100.0)]);
let price = genai_prices::calculate(&PriceRequest::new("gpt-5", usage).with_provider_id("openai"))?;

println!("${:.6}", price.total_price);
# Ok::<(), genai_prices::Error>(())
```

`calculate` uses pricing data embedded at release time. Pass a provider ID when you know the provider. This avoids
an ambiguous model name selecting the wrong provider.

Requests are priced at the rates in effect when they were made. `timestamp` defaults to now; set it with
`with_timestamp`, which takes anything convertible to `std::time::SystemTime`, including `chrono`, `jiff` and
`time` date-times.

## Request pricing context

```rust
use std::time::{Duration, UNIX_EPOCH};

use genai_prices::{PriceRequest, Usage, UsageKey};

let usage = Usage::from([(UsageKey::INPUT_TOKENS, 1_000_000.0), (UsageKey::OUTPUT_TOKENS, 1_000_000.0)]);
let request = PriceRequest::new("o3", usage)
    .with_provider_id("openai")
    .with_timestamp(UNIX_EPOCH + Duration::from_secs(1_791_763_200)) // 2026-10-12
    .with_price_context("service_tier", "flex");

assert_eq!(genai_prices::calculate(&request)?.total_price, 5.0);
# Ok::<(), genai_prices::Error>(())
```

You pass the price context explicitly to select request-specific prices.
Use the `service_tier` reported in OpenAI's response. A priority request can be downgraded and report `default`.
`auto` is a request setting and does not identify the rate you were charged. Extraction does not infer a context.
Tier variants are specific to their provider. If model lookup falls back to another provider, you receive the
standard-price estimate; the fallback provider's tier rates are not applied.

OpenAI variants cover `flex`, `priority`, and `fast` where the published rate table supports them.
`default` selects standard prices on these models. Omit the context for ordinary standard pricing.

If a context matches no variant, you receive the standard-price estimate.
This includes unsupported models, unknown tiers, misspelled keys, and dates without verified tier rates.
The bundled tier rates are verified from October 12, 2026; earlier tier history is not modeled.

## Batch API

```rust
use std::time::{Duration, UNIX_EPOCH};

use genai_prices::{PriceRequest, Usage, UsageKey};

let usage = Usage::from([(UsageKey::INPUT_TOKENS, 1_000_000.0), (UsageKey::OUTPUT_TOKENS, 1_000_000.0)]);
let request = PriceRequest::new("o3", usage)
    .with_provider_id("openai")
    .with_timestamp(UNIX_EPOCH + Duration::from_secs(1_791_936_000)) // 2026-10-14
    .with_price_context("processing", "batch");

assert_eq!(genai_prices::calculate(&request)?.total_price, 5.0);
# Ok::<(), genai_prices::Error>(())
```

You pass `("processing", "batch")` for usage from a provider's batch API. Most providers do not mark batch results in
the response, so you set it yourself. Batch is a separate key from `service_tier` because it is a way of submitting
requests, not a tier: OpenAI batch results report `service_tier: "default"`.

Batch rates are bundled for Anthropic, OpenAI, Google, Mistral, Groq and xAI, verified from October 14, 2026.
A model the provider does not serve in batch returns the standard-price estimate.

## Extract usage from a response

```rust
use genai_prices::{ExtractRequest, PriceRequest};

let body = r#"{"model": "gpt-5", "usage": {"input_tokens": 1000, "output_tokens": 100}}"#;
let extracted = genai_prices::extract_usage(
    &ExtractRequest::new(body).with_provider_id("openai").with_api_flavor("responses"),
)?;

let model = extracted.model.unwrap_or_default();
let request = PriceRequest::new(model, extracted.usage).with_provider_id(extracted.provider_id);
println!("${:.6}", genai_prices::calculate(&request)?.total_price);
# Ok::<(), genai_prices::Error>(())
```

The API flavor selects the response shape used by a provider. For example, OpenAI exposes `chat` and `responses`
shapes.

## Load current pricing data

The crate does not make network requests. Download [`REMOTE_DATA_URL`] with the HTTP client you already use and
build a `Calculator` from the body:

```rust,ignore
use genai_prices::{Calculator, PriceRequest, REMOTE_DATA_URL, Usage, UsageKey};

let body = reqwest::blocking::get(REMOTE_DATA_URL)?.error_for_status()?.bytes()?;
let calculator = Calculator::from_json(&body)?;

let usage = Usage::from([(UsageKey::INPUT_TOKENS, 1_000.0)]);
let price = calculator.calculate(&PriceRequest::new("gpt-5", usage).with_provider_id("openai"))?;
println!("${:.6}", price.total_price);
```

`Calculator::from_json` creates an immutable snapshot. A failed download or invalid payload cannot replace a
calculator that your application is already using; share it across threads with an `Arc` and swap it (e.g. with
`arc-swap`) once a new snapshot loads.
