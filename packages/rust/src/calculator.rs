use std::borrow::Cow;
use std::fmt;
use std::time::SystemTime;

use crate::decode::decode_providers;
use crate::error::{Error, ErrorKind, Result, validate_number};
use crate::matching::{ModelMatch, find_model, find_provider, find_provider_by_id};
use crate::model::{Constraint, Model, ModelPrice, Provider};
use crate::request::{PriceCalculation, PriceRequest};
use crate::time::Timestamp;
use crate::units::{BUNDLED_REGISTRY, Registry, calculate_model_price, calculation_warnings, validate_model_price};
use crate::usage::{Usage, UsageKey};

#[cfg(feature = "bundled")]
static BUNDLED_CALCULATOR: std::sync::LazyLock<Calculator> = std::sync::LazyLock::new(|| {
    Calculator::from_json(include_bytes!("../data/prices.json")).expect("bundled provider data is valid")
});

/// Calculates prices using one immutable provider-data snapshot.
///
/// [`Calculator::bundled`] returns the snapshot embedded at release time; [`Calculator::from_json`] loads a
/// newer one, e.g. from [`REMOTE_DATA_URL`](crate::REMOTE_DATA_URL). A calculator is `Send + Sync`; share it
/// across threads behind an [`Arc`](std::sync::Arc).
pub struct Calculator {
    pub(crate) providers: Vec<Provider>,
    pub(crate) registry: &'static Registry,
}

impl fmt::Debug for Calculator {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Calculator")
            .field("providers", &self.providers.len())
            .field("models", &self.providers.iter().map(|provider| provider.models.len()).sum::<usize>())
            .finish_non_exhaustive()
    }
}

impl Calculator {
    /// Returns the calculator for the provider data bundled with this release.
    ///
    /// The data is decoded on first use, which takes tens of milliseconds; call this at startup to keep that
    /// off the first request.
    ///
    /// # Panics
    ///
    /// Panics if the bundled data fails to decode. The crate's tests decode it, so this indicates a broken
    /// release.
    #[cfg(feature = "bundled")]
    #[must_use]
    pub fn bundled() -> &'static Calculator {
        &BUNDLED_CALCULATOR
    }

    /// Creates a calculator from a v2 provider-data payload.
    ///
    /// # Errors
    ///
    /// Returns an [`ErrorKind::InvalidData`] error if the payload is not valid JSON or fails validation.
    pub fn from_json(data: impl AsRef<[u8]>) -> Result<Self> {
        let registry = &*BUNDLED_REGISTRY;
        let providers = decode_providers(data.as_ref(), registry)?;
        Ok(Self { providers, registry })
    }

    /// Calculates the price of one API call.
    ///
    /// # Errors
    ///
    /// Returns an [`ErrorKind::ProviderNotFound`] or [`ErrorKind::ModelNotFound`] error if nothing matches the
    /// request, and an [`ErrorKind::InvalidUsage`] error if usage values are negative, non-finite or
    /// inconsistent with each other.
    pub fn calculate(&self, request: &PriceRequest<'_>) -> Result<PriceCalculation> {
        let provider_id = non_empty(request.provider_id.map(str::trim));
        let provider_api_url = non_empty(request.provider_api_url);
        if provider_id.is_some() && provider_api_url.is_some() {
            return Err(Error::new(ErrorKind::InvalidUsage, "provider ID and provider API URL are mutually exclusive"));
        }
        let model_id = request.model.trim().to_lowercase();
        if model_id.is_empty() {
            return Err(Error::new(ErrorKind::ModelNotFound, "model is required"));
        }
        let (provider_id, model_id) = self.route_litellm(provider_id, model_id)?;
        let provider_id = provider_id.as_deref();

        let selected = find_provider(&self.providers, &model_id, provider_id, provider_api_url)?.ok_or_else(|| {
            Error::new(
                ErrorKind::ProviderNotFound,
                format!(
                    "model={model_id:?} provider_id={:?} provider_api_url={:?}",
                    provider_id.unwrap_or_default(),
                    provider_api_url.unwrap_or_default(),
                ),
            )
        })?;
        let provider = &self.providers[selected];
        let matched = find_model(&self.providers, selected, &model_id)?.ok_or_else(|| {
            Error::new(ErrorKind::ModelNotFound, format!("{model_id:?} in provider {:?}", provider.id))
        })?;

        let timestamp = Timestamp::from(request.timestamp.unwrap_or_else(SystemTime::now));
        let prices = resolve_price_variants(&matched, selected, timestamp, request);
        if !request.price_context.is_empty() {
            validate_model_price(&prices, self.registry)
                .map_err(|message| Error::new(ErrorKind::InvalidData, message))?;
        }
        for (key, value) in request.usage {
            if self.registry.is_reported(key.as_str()) {
                validate_number(key.as_str(), value)?;
            }
        }
        let usage = apply_provider_billing(provider, matched.model, request.usage);
        let calculated = calculate_model_price(&usage, &prices, self.registry)?;
        Ok(PriceCalculation {
            input_price: calculated.input,
            output_price: calculated.output,
            total_price: calculated.total,
            provider_id: provider.id.clone(),
            model_id: matched.model.id.clone(),
            warnings: calculation_warnings(request.usage, &prices, self.registry),
        })
    }

    /// LiteLLM is a proxy that prefixes models with their real provider, e.g. `anthropic/claude-sonnet-5`.
    /// When that prefix names a known provider, price the request as that provider's model.
    fn route_litellm<'a>(
        &self,
        provider_id: Option<&'a str>,
        model_id: String,
    ) -> Result<(Option<Cow<'a, str>>, String)> {
        let routed = provider_id
            .filter(|id| id.eq_ignore_ascii_case("litellm"))
            .and_then(|_| model_id.split_once('/'))
            .filter(|(provider, model)| !provider.is_empty() && !model.is_empty());
        if let Some((provider, model)) = routed {
            if find_provider_by_id(&self.providers, provider)?.is_some() {
                return Ok((Some(Cow::Owned(provider.to_owned())), model.to_owned()));
            }
        }
        Ok((provider_id.map(Cow::Borrowed), model_id))
    }
}

/// Calculates a price using the bundled provider data. See [`Calculator::calculate`].
///
/// # Errors
///
/// See [`Calculator::calculate`].
///
/// # Panics
///
/// See [`Calculator::bundled`].
#[cfg(feature = "bundled")]
pub fn calculate(request: &PriceRequest<'_>) -> Result<PriceCalculation> {
    Calculator::bundled().calculate(request)
}

pub(crate) fn non_empty(value: Option<&str>) -> Option<&str> {
    value.filter(|value| !value.is_empty())
}

/// Applies request-specific price variants over the standard prices for `timestamp`.
///
/// Variants belong to the provider that defines them, so a model found through a fallback provider is
/// priced at its standard rates. Each price key takes the value from the first active matching variant.
fn resolve_price_variants<'a>(
    matched: &ModelMatch<'a>,
    selected: usize,
    timestamp: Timestamp,
    request: &PriceRequest<'_>,
) -> Cow<'a, ModelPrice> {
    let model: &Model = matched.model;
    let standard = model.active_price(timestamp);
    if request.price_context.is_empty() || matched.provider != selected {
        return Cow::Borrowed(standard);
    }
    let mut resolved = standard.clone();
    let mut overridden = Vec::new();
    for variant in &model.price_variants {
        if !Constraint::is_active(variant.constraint.as_ref(), timestamp) {
            continue;
        }
        if !variant.when.iter().all(|(key, value)| request.context_value(key) == Some(value.as_str())) {
            continue;
        }
        for (key, price) in &variant.prices {
            if !overridden.contains(&key) {
                resolved.insert(key.clone(), price.clone());
                overridden.push(key);
            }
        }
    }
    Cow::Owned(resolved)
}

/// Groq bills Whisper transcriptions for at least ten seconds of audio.
fn apply_provider_billing<'a>(provider: &Provider, model: &Model, usage: &'a Usage) -> Cow<'a, Usage> {
    if provider.id != "groq" || !matches!(model.id.as_str(), "whisper-large-v3" | "whisper-large-v3-turbo") {
        return Cow::Borrowed(usage);
    }
    let reported = match (usage.get(UsageKey::AUDIO_SECONDS), usage.get(UsageKey::INPUT_AUDIO_SECONDS)) {
        (Some(audio), _) if audio != 0.0 => audio,
        (_, Some(input_audio)) => input_audio,
        (_, None) => return Cow::Borrowed(usage),
    };
    let billed = if reported > 0.0 { reported.max(10.0) } else { reported };
    let mut billed_usage = usage.clone();
    billed_usage.insert(UsageKey::AUDIO_SECONDS, billed);
    billed_usage.insert(UsageKey::INPUT_AUDIO_SECONDS, billed);
    Cow::Owned(billed_usage)
}
