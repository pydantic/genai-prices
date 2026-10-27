use std::time::SystemTime;

use serde::ser::{Serialize, SerializeStruct, Serializer}; // codespell:ignore ser
use serde_json::Value;

use crate::usage::Usage;

/// Describes one price calculation. Everything is borrowed, so building a request does not allocate unless
/// it carries a price context.
///
/// ```
/// use genai_prices::{PriceRequest, Usage, UsageKey};
///
/// let usage = Usage::from([(UsageKey::INPUT_TOKENS, 1_000.0)]);
/// let request = PriceRequest::new("gpt-5", &usage)
///     .with_provider_id("openai")
///     .with_price_context("service_tier", "flex");
/// assert_eq!(request.provider_id, Some("openai"));
/// ```
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub struct PriceRequest<'a> {
    /// The values reported by the provider.
    pub usage: &'a Usage,
    /// The model reference as reported by the provider or passed by the caller, matched case-insensitively.
    pub model: &'a str,
    /// Selects the provider by ID or alias, ignoring surrounding whitespace. Takes precedence over
    /// `provider_api_url`.
    pub provider_id: Option<&'a str>,
    /// Selects the provider by API URL when `provider_id` is not set.
    pub provider_api_url: Option<&'a str>,
    /// When the request was made. Defaults to now; selects date- and time-constrained prices.
    pub timestamp: Option<SystemTime>,
    /// Request-specific pricing context, such as `[("service_tier", "flex")]`. Later entries win over earlier
    /// entries with the same key.
    pub price_context: Vec<(&'a str, &'a str)>,
    /// Set by [`ExtractedUsage::price_request`] to price the model extraction matched.
    pub(crate) resolved: Option<ResolvedModel<'a>>,
}

impl<'a> PriceRequest<'a> {
    /// Creates a request for `model` with the given usage.
    #[must_use]
    pub fn new(model: &'a str, usage: &'a Usage) -> Self {
        Self {
            usage,
            model,
            provider_id: None,
            provider_api_url: None,
            timestamp: None,
            price_context: Vec::new(),
            resolved: None,
        }
    }

    /// Selects the provider by ID or alias.
    #[must_use]
    pub fn with_provider_id(mut self, provider_id: &'a str) -> Self {
        self.provider_id = Some(provider_id);
        self
    }

    /// Selects the provider by API URL.
    #[must_use]
    pub fn with_provider_api_url(mut self, provider_api_url: &'a str) -> Self {
        self.provider_api_url = Some(provider_api_url);
        self
    }

    /// Sets when the request was made. Accepts `chrono`, `jiff` and `time` date-times through their
    /// conversions to [`SystemTime`].
    #[must_use]
    pub fn with_timestamp(mut self, timestamp: impl Into<SystemTime>) -> Self {
        self.timestamp = Some(timestamp.into());
        self
    }

    /// Adds one entry to the request-specific pricing context.
    #[must_use]
    pub fn with_price_context(mut self, key: &'a str, value: &'a str) -> Self {
        self.price_context.push((key, value));
        self
    }

    /// The value of a price-context key, honouring the last entry for duplicated keys.
    pub(crate) fn context_value(&self, key: &str) -> Option<&'a str> {
        self.price_context.iter().rev().find(|(candidate, _)| *candidate == key).map(|(_, value)| *value)
    }
}

/// Prices in US dollars and the identifiers that were matched.
///
/// Prices are `f64`, as in the Go and JavaScript packages. The Python package computes with `Decimal`; the
/// shared golden dataset agrees with it to within `5e-9` dollars per request.
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

impl Serialize for PriceCalculation {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut state = serializer.serialize_struct("PriceCalculation", 6)?;
        state.serialize_field("input_price", &self.input_price)?;
        state.serialize_field("output_price", &self.output_price)?;
        state.serialize_field("total_price", &self.total_price)?;
        state.serialize_field("provider_id", &self.provider_id)?;
        state.serialize_field("model_id", &self.model_id)?;
        state.serialize_field("warnings", &self.warnings)?;
        state.end()
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub(crate) enum Body<'a> {
    Json(&'a [u8]),
    Value(&'a Value),
}

/// Describes usage extraction from a response body.
///
/// ```
/// use genai_prices::ExtractRequest;
///
/// let body = r#"{"usage": {"input_tokens": 1}}"#;
/// let request = ExtractRequest::new(body).with_provider_id("openai").with_api_flavor("responses");
/// assert_eq!(request.api_flavor, Some("responses"));
///
/// // A body you have already parsed is used as is.
/// let parsed: serde_json::Value = serde_json::from_str(body).unwrap();
/// let request = ExtractRequest::from_value(&parsed).with_provider_id("openai");
/// ```
#[derive(Debug, Clone, Copy, PartialEq)]
#[non_exhaustive]
pub struct ExtractRequest<'a> {
    pub(crate) body: Body<'a>,
    /// Selects the provider by ID or alias, ignoring surrounding whitespace. Takes precedence over
    /// `provider_api_url`.
    pub provider_id: Option<&'a str>,
    /// Selects the provider by API URL when `provider_id` is not set.
    pub provider_api_url: Option<&'a str>,
    /// Selects the response shape, e.g. `chat` or `responses`. Defaults to `default`.
    pub api_flavor: Option<&'a str>,
}

impl<'a> ExtractRequest<'a> {
    /// Creates a request for a raw JSON response body.
    #[must_use]
    pub fn new(response_json: &'a (impl AsRef<[u8]> + ?Sized)) -> Self {
        Self::with_body(Body::Json(response_json.as_ref()))
    }

    /// Creates a request for a response body that has already been parsed.
    #[must_use]
    pub fn from_value(response: &'a Value) -> Self {
        Self::with_body(Body::Value(response))
    }

    fn with_body(body: Body<'a>) -> Self {
        Self { body, provider_id: None, provider_api_url: None, api_flavor: None }
    }

    /// Selects the provider by ID or alias.
    #[must_use]
    pub fn with_provider_id(mut self, provider_id: &'a str) -> Self {
        self.provider_id = Some(provider_id);
        self
    }

    /// Selects the provider by API URL.
    #[must_use]
    pub fn with_provider_api_url(mut self, provider_api_url: &'a str) -> Self {
        self.provider_api_url = Some(provider_api_url);
        self
    }

    /// Selects the response shape used by the provider.
    #[must_use]
    pub fn with_api_flavor(mut self, api_flavor: &'a str) -> Self {
        self.api_flavor = Some(api_flavor);
        self
    }
}

/// Usage read from a response, with the model it reports matched against the provider data.
#[derive(Debug, Clone, Default, PartialEq)]
#[non_exhaustive]
pub struct ExtractedUsage {
    /// The extracted usage values.
    pub usage: Usage,
    /// The ID of the matched model, or `None` when the response does not report a model.
    pub model_id: Option<String>,
    /// The ID of the matched provider.
    pub provider_id: String,
    /// Extractor destinations that this release cannot represent.
    pub warnings: Vec<String>,
    /// The provider that defines the model, which differs from `provider_id` for fallback providers.
    pub(crate) model_provider_id: Option<String>,
}

impl ExtractedUsage {
    /// A request to price this usage with the matched model.
    ///
    /// The model is priced as matched, not by matching its ID again, so calculate the request with the same
    /// provider data that extracted it. Returns `None` when the response did not report a model.
    #[must_use]
    pub fn price_request(&self) -> Option<PriceRequest<'_>> {
        let model_id = self.model_id.as_deref()?;
        let mut request = PriceRequest::new(model_id, &self.usage).with_provider_id(&self.provider_id);
        request.resolved = Some(ResolvedModel { model_provider_id: self.model_provider_id.as_deref()?, model_id });
        Some(request)
    }
}

impl Serialize for ExtractedUsage {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut state = serializer.serialize_struct("ExtractedUsage", 4)?;
        state.serialize_field("usage", &self.usage)?;
        state.serialize_field("model_id", &self.model_id)?;
        state.serialize_field("provider_id", &self.provider_id)?;
        state.serialize_field("warnings", &self.warnings)?;
        state.end()
    }
}

/// Usage and the raw model reference read from a response, without matching the model.
#[derive(Debug, Clone, Default, PartialEq)]
#[non_exhaustive]
pub struct ProviderUsage {
    /// The extracted usage values.
    pub usage: Usage,
    /// The model reference exactly as the response reports it, if any.
    pub model_ref: Option<String>,
    /// The ID of the matched provider.
    pub provider_id: String,
    /// Extractor destinations that this release cannot represent.
    pub warnings: Vec<String>,
}

impl Serialize for ProviderUsage {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut state = serializer.serialize_struct("ProviderUsage", 4)?;
        state.serialize_field("usage", &self.usage)?;
        state.serialize_field("model_ref", &self.model_ref)?;
        state.serialize_field("provider_id", &self.provider_id)?;
        state.serialize_field("warnings", &self.warnings)?;
        state.end()
    }
}

/// A model already matched by extraction, identified by the provider that defines it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct ResolvedModel<'a> {
    pub(crate) model_provider_id: &'a str,
    pub(crate) model_id: &'a str,
}
