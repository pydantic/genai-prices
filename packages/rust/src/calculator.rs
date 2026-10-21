use std::borrow::Cow;
use std::collections::BTreeMap;
use std::sync::LazyLock;
use std::time::SystemTime;

use crate::decode::decode_providers;
use crate::error::{Error, Result, validate_number};
use crate::matching::{ModelMatch, find_model, find_provider, find_provider_by_id};
use crate::model::{Constraint, Model, ModelPrice, Provider};
use crate::request::{PriceCalculation, PriceRequest};
use crate::time::Instant;
use crate::units::{BUNDLED_REGISTRY, Registry, calculate_model_price, calculation_warnings, validate_model_price};
use crate::usage::{Usage, UsageKey};

static BUNDLED_PROVIDER_DATA: &[u8] = include_bytes!("../data/prices.json");

static BUNDLED_CALCULATOR: LazyLock<Calculator> =
    LazyLock::new(|| Calculator::from_json(BUNDLED_PROVIDER_DATA).expect("bundled provider data is valid"));

/// Calculates prices using one immutable provider-data snapshot.
///
/// [`Calculator::bundled`] returns the snapshot embedded at release time; [`Calculator::from_json`] loads a
/// newer one, e.g. from [`REMOTE_DATA_URL`](crate::REMOTE_DATA_URL). A calculator is cheap to share
/// across threads behind an [`Arc`](std::sync::Arc).
#[derive(Debug)]
pub struct Calculator {
    pub(crate) providers: Vec<Provider>,
    pub(crate) registry: &'static Registry,
}

impl Calculator {
    /// Returns the calculator for the provider data bundled with this release.
    ///
    /// The data is decoded on first use.
    #[must_use]
    pub fn bundled() -> &'static Calculator {
        &BUNDLED_CALCULATOR
    }

    /// Creates a calculator from a v2 provider-data payload.
    ///
    /// # Errors
    ///
    /// Returns [`Error::InvalidData`] if the payload is not valid JSON or fails validation.
    pub fn from_json(data: impl AsRef<[u8]>) -> Result<Self> {
        let registry = &*BUNDLED_REGISTRY;
        let providers = decode_providers(data.as_ref(), registry).map_err(Error::InvalidData)?;
        Ok(Self { providers, registry })
    }

    /// Calculates the price of one API call.
    ///
    /// # Errors
    ///
    /// Returns [`Error::ProviderNotFound`] or [`Error::ModelNotFound`] if nothing matches the request, and
    /// [`Error::InvalidUsage`] if usage values are negative, non-finite or inconsistent with each other.
    pub fn calculate(&self, request: &PriceRequest) -> Result<PriceCalculation> {
        let mut provider_id = non_empty(request.provider_id.as_deref().map(str::trim));
        let provider_api_url = non_empty(request.provider_api_url.as_deref());
        if provider_id.is_some() && provider_api_url.is_some() {
            return Err(Error::InvalidUsage("provider ID and provider API URL are mutually exclusive".into()));
        }
        let mut model_id = request.model.trim().to_lowercase();
        if model_id.is_empty() {
            return Err(Error::ModelNotFound("model is required".into()));
        }
        let litellm_route = provider_id
            .filter(|id| id.eq_ignore_ascii_case("litellm"))
            .and_then(|_| model_id.split_once('/'))
            .filter(|(provider, model)| !provider.is_empty() && !model.is_empty())
            .map(|(provider, model)| (provider.to_owned(), model.to_owned()));
        let routed_provider;
        if let Some((routed, model)) = litellm_route {
            if find_provider_by_id(&self.providers, &routed)?.is_some() {
                routed_provider = routed;
                provider_id = Some(&routed_provider);
                model_id = model;
            }
        }

        let selected = find_provider(&self.providers, &model_id, provider_id, provider_api_url)?.ok_or_else(|| {
            Error::ProviderNotFound(format!(
                "model={model_id:?} provider_id={:?} provider_api_url={:?}",
                provider_id.unwrap_or_default(),
                provider_api_url.unwrap_or_default(),
            ))
        })?;
        let provider = &self.providers[selected];
        let matched = find_model(&self.providers, selected, &model_id)?
            .ok_or_else(|| Error::ModelNotFound(format!("{model_id:?} in provider {:?}", provider.id)))?;

        let timestamp = Instant::from(request.timestamp.unwrap_or_else(SystemTime::now));
        let prices = resolve_price_variants(&matched, selected, timestamp, &request.price_context);
        if !request.price_context.is_empty() {
            validate_model_price(&prices, self.registry).map_err(Error::InvalidData)?;
        }
        for (key, &value) in &request.usage {
            if self.registry.is_reported(key.as_str()) {
                validate_number(key.as_str(), value)?;
            }
        }
        let usage = apply_provider_billing(provider, matched.model, &request.usage);
        let calculated = calculate_model_price(&usage, &prices, self.registry)?;
        Ok(PriceCalculation {
            input_price: calculated.input,
            output_price: calculated.output,
            total_price: calculated.total,
            provider_id: provider.id.clone(),
            model_id: matched.model.id.clone(),
            warnings: calculation_warnings(&request.usage, &prices, self.registry),
        })
    }
}

/// Calculates a price using the bundled provider data. See [`Calculator::calculate`].
///
/// # Errors
///
/// See [`Calculator::calculate`].
pub fn calculate(request: &PriceRequest) -> Result<PriceCalculation> {
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
    timestamp: Instant,
    context: &BTreeMap<String, String>,
) -> Cow<'a, ModelPrice> {
    let model: &Model = matched.model;
    let standard = model.active_price(timestamp);
    if context.is_empty() || matched.provider != selected {
        return Cow::Borrowed(standard);
    }
    let mut resolved = standard.clone();
    let mut overridden = Vec::new();
    for variant in &model.price_variants {
        if !Constraint::is_active(variant.constraint.as_ref(), timestamp) {
            continue;
        }
        if !variant.when.iter().all(|(key, value)| context.get(key) == Some(value)) {
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
    let reported =
        match (usage.get(UsageKey::AUDIO_SECONDS.as_str()), usage.get(UsageKey::INPUT_AUDIO_SECONDS.as_str())) {
            (Some(&audio), _) if audio != 0.0 => audio,
            (_, Some(&input_audio)) => input_audio,
            (_, None) => return Cow::Borrowed(usage),
        };
    let billed = if reported > 0.0 { reported.max(10.0) } else { reported };
    let mut billed_usage = usage.clone();
    billed_usage.insert(UsageKey::AUDIO_SECONDS, billed);
    billed_usage.insert(UsageKey::INPUT_AUDIO_SECONDS, billed);
    Cow::Owned(billed_usage)
}
