use std::collections::BTreeMap;
use std::time::SystemTime;

use crate::usage::Usage;

/// Describes one price calculation.
///
/// ```
/// use genai_prices::{PriceRequest, Usage, UsageKey};
///
/// let request = PriceRequest::new("gpt-5", Usage::from([(UsageKey::INPUT_TOKENS, 1_000.0)]))
///     .with_provider_id("openai")
///     .with_price_context("service_tier", "flex");
/// assert_eq!(request.provider_id.as_deref(), Some("openai"));
/// ```
#[derive(Debug, Clone, Default, PartialEq)]
#[non_exhaustive]
pub struct PriceRequest {
    /// The values reported by the provider.
    pub usage: Usage,
    /// The model reference as reported by the provider or passed by the caller.
    pub model: String,
    /// Selects the provider by ID or alias. Mutually exclusive with `provider_api_url`.
    pub provider_id: Option<String>,
    /// Selects the provider by API URL. Mutually exclusive with `provider_id`.
    pub provider_api_url: Option<String>,
    /// When the request was made. Defaults to now; selects date- and time-constrained prices.
    pub timestamp: Option<SystemTime>,
    /// Request-specific pricing context, such as `{"service_tier": "flex"}`.
    pub price_context: BTreeMap<String, String>,
}

impl PriceRequest {
    /// Creates a request for `model` with the given usage.
    #[must_use]
    pub fn new(model: impl Into<String>, usage: Usage) -> Self {
        Self { usage, model: model.into(), ..Self::default() }
    }

    /// Selects the provider by ID or alias.
    #[must_use]
    pub fn with_provider_id(mut self, provider_id: impl Into<String>) -> Self {
        self.provider_id = Some(provider_id.into());
        self
    }

    /// Selects the provider by API URL.
    #[must_use]
    pub fn with_provider_api_url(mut self, provider_api_url: impl Into<String>) -> Self {
        self.provider_api_url = Some(provider_api_url.into());
        self
    }

    /// Sets when the request was made.
    #[must_use]
    pub fn with_timestamp(mut self, timestamp: impl Into<SystemTime>) -> Self {
        self.timestamp = Some(timestamp.into());
        self
    }

    /// Adds one entry to the request-specific pricing context.
    #[must_use]
    pub fn with_price_context(mut self, key: impl Into<String>, value: impl Into<String>) -> Self {
        self.price_context.insert(key.into(), value.into());
        self
    }
}

/// Prices in US dollars and the identifiers that were matched.
#[derive(Debug, Clone, Default, PartialEq)]
#[non_exhaustive]
pub struct PriceCalculation {
    /// The price of input usage.
    pub input_price: f64,
    /// The price of output usage.
    pub output_price: f64,
    /// The total price, including usage that is neither input nor output (e.g. requests).
    pub total_price: f64,
    /// The ID of the matched provider.
    pub provider_id: String,
    /// The ID of the matched model.
    pub model_id: String,
    /// Usage or price keys that this release cannot price, e.g. ones added by newer provider data.
    pub warnings: Vec<String>,
}

/// Describes usage extraction from a raw JSON response body.
///
/// ```
/// use genai_prices::ExtractRequest;
///
/// let request = ExtractRequest::new(r#"{"usage": {"input_tokens": 1}}"#)
///     .with_provider_id("openai")
///     .with_api_flavor("responses");
/// assert_eq!(request.api_flavor.as_deref(), Some("responses"));
/// ```
#[derive(Debug, Clone, Default, PartialEq, Eq)]
#[non_exhaustive]
pub struct ExtractRequest {
    /// The raw JSON response body.
    pub response_json: Vec<u8>,
    /// Selects the provider by ID or alias. Mutually exclusive with `provider_api_url`.
    pub provider_id: Option<String>,
    /// Selects the provider by API URL. Mutually exclusive with `provider_id`.
    pub provider_api_url: Option<String>,
    /// Selects the response shape, e.g. `chat` or `responses`. Defaults to `default`.
    pub api_flavor: Option<String>,
}

impl ExtractRequest {
    /// Creates a request for the given JSON response body.
    #[must_use]
    pub fn new(response_json: impl Into<Vec<u8>>) -> Self {
        Self { response_json: response_json.into(), ..Self::default() }
    }

    /// Selects the provider by ID or alias.
    #[must_use]
    pub fn with_provider_id(mut self, provider_id: impl Into<String>) -> Self {
        self.provider_id = Some(provider_id.into());
        self
    }

    /// Selects the provider by API URL.
    #[must_use]
    pub fn with_provider_api_url(mut self, provider_api_url: impl Into<String>) -> Self {
        self.provider_api_url = Some(provider_api_url.into());
        self
    }

    /// Selects the response shape used by the provider.
    #[must_use]
    pub fn with_api_flavor(mut self, api_flavor: impl Into<String>) -> Self {
        self.api_flavor = Some(api_flavor.into());
        self
    }
}

/// Usage and model information read from a response.
#[derive(Debug, Clone, Default, PartialEq)]
#[non_exhaustive]
pub struct ExtractedUsage {
    /// The extracted usage values.
    pub usage: Usage,
    /// The model reported by the response, if any.
    pub model: Option<String>,
    /// The ID of the matched provider.
    pub provider_id: String,
    /// Extractor destinations that this release cannot represent.
    pub warnings: Vec<String>,
}
