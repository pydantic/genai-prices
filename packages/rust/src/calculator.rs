use std::borrow::Cow;
use std::fmt;
use std::time::SystemTime;

use crate::data_units::UNIT_COUNT;
use crate::decode::decode_providers;
use crate::error::{Error, ErrorKind, Result, validate_number};
use crate::matching::{ModelMatch, find_model, find_provider, find_provider_by_id, fold_case};
use crate::model::{Constraint, Model, Provider};
use crate::request::{PriceCalculation, PriceRequest, ResolvedModel};
use crate::time::Timestamp;
use crate::units::{
    BUNDLED_REGISTRY, PriceSet, Registry, calculate_model_price, calculation_warnings, validate_price_set,
};
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
        let model_ref = fold_case(request.model);
        let (selected, matched) = match request.resolved {
            Some(resolved) => self.find_resolved_model(request.provider_id.unwrap_or_default(), resolved)?,
            None => self.find_provider_model(&model_ref, request.provider_id, request.provider_api_url)?,
        };
        let provider = &self.providers[selected];

        let timestamp = Timestamp::from(request.timestamp.unwrap_or_else(SystemTime::now));
        let (prices, unknown_price_keys) = self.resolve_prices(&matched, selected, timestamp, request);
        if !request.price_context.is_empty() {
            validate_price_set(&prices, self.registry)
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
            warnings: calculation_warnings(request.usage, unknown_price_keys, self.registry),
        })
    }

    /// Finds the provider and model for a lowercased model reference, as `DataSnapshot.find_provider_model` does
    /// in the Python package.
    fn find_provider_model<'a>(
        &'a self,
        model_ref: &str,
        provider_id: Option<&str>,
        provider_api_url: Option<&str>,
    ) -> Result<(usize, ModelMatch<'a>)> {
        let (mut model_ref, mut provider_id) = (model_ref, provider_id);
        // LiteLLM is a proxy that prefixes models with their real provider, e.g. `anthropic/claude-sonnet-5`. When the
        // prefix names a known provider, price the request as that provider's model.
        if provider_id.is_some_and(|id| id.eq_ignore_ascii_case("litellm")) {
            if let Some((actual_provider_id, actual_model_ref)) = model_ref.split_once('/') {
                if !actual_provider_id.is_empty() && find_provider_by_id(&self.providers, actual_provider_id)?.is_some()
                {
                    provider_id = Some(actual_provider_id);
                    model_ref = actual_model_ref;
                }
            }
        }

        let selected = find_provider(&self.providers, model_ref, provider_id, provider_api_url)?
            .ok_or_else(|| provider_lookup_error(model_ref, provider_id, provider_api_url))?;
        let matched = find_model(&self.providers, selected, model_ref)?.ok_or_else(|| {
            let provider = &self.providers[selected].id;
            Error::new(
                ErrorKind::ModelNotFound,
                format!("unable to find model with model_ref={model_ref:?} in {provider}"),
            )
        })?;
        Ok((selected, matched))
    }

    /// Finds a model that extraction already matched, by the IDs it recorded.
    fn find_resolved_model<'a>(
        &'a self,
        provider_id: &str,
        resolved: ResolvedModel<'_>,
    ) -> Result<(usize, ModelMatch<'a>)> {
        let not_found = || {
            Error::new(
                ErrorKind::ModelNotFound,
                format!(
                    "model {:?} of provider {:?} is not in this data",
                    resolved.model_id, resolved.model_provider_id
                ),
            )
        };
        let index_of = |id: &str| self.providers.iter().position(|provider| provider.id == id);
        let selected = index_of(provider_id).ok_or_else(not_found)?;
        let provider = index_of(resolved.model_provider_id).ok_or_else(not_found)?;
        let model =
            self.providers[provider].models.iter().find(|model| model.id == resolved.model_id).ok_or_else(not_found)?;
        Ok((selected, ModelMatch { provider, model }))
    }

    /// The prices for `timestamp` with any matching request-specific variants applied, plus the price keys this
    /// release cannot price.
    ///
    /// Variants belong to the provider that defines them, so a model found through a fallback provider is
    /// priced at its standard rates. Each price key takes the value from the first active matching variant.
    fn resolve_prices<'a>(
        &self,
        matched: &ModelMatch<'a>,
        selected: usize,
        timestamp: Timestamp,
        request: &PriceRequest<'_>,
    ) -> (PriceSet<'a>, Vec<&'a str>) {
        let model: &'a Model = matched.model;
        let standard = model.active_price(timestamp);
        let mut prices = PriceSet::new(standard, self.registry);
        let mut unknown: Vec<&str> =
            standard.keys().map(String::as_str).filter(|key| self.registry.by_price_key(key).is_none()).collect();
        if request.price_context.is_empty() || matched.provider != selected {
            return (prices, unknown);
        }
        let mut overridden = [false; UNIT_COUNT];
        for variant in &model.price_variants {
            if !Constraint::is_active(variant.constraint.as_ref(), timestamp) {
                continue;
            }
            if !variant.when.iter().all(|(key, value)| request.context_value(key) == Some(value.as_str())) {
                continue;
            }
            for (key, price) in &variant.prices {
                match self.registry.by_price_key(key) {
                    Some(unit) if !overridden[unit] => {
                        prices.set(unit, price);
                        overridden[unit] = true;
                    }
                    Some(_) => {}
                    None => unknown.push(key),
                }
            }
        }
        (prices, unknown)
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

/// The error for a provider lookup that matched nothing, naming the selector that was used.
pub(crate) fn provider_lookup_error(
    model_ref: &str,
    provider_id: Option<&str>,
    provider_api_url: Option<&str>,
) -> Error {
    let message = match (provider_id, provider_api_url) {
        (Some(id), _) if !id.eq_ignore_ascii_case("litellm") => format!("unable to find provider provider_id={id:?}"),
        (_, Some(url)) => format!("unable to find provider provider_api_url={url:?}"),
        _ => format!("unable to find provider with model matching {model_ref:?}"),
    };
    Error::new(ErrorKind::ProviderNotFound, message)
}

pub(crate) fn non_empty(value: Option<&str>) -> Option<&str> {
    value.filter(|value| !value.is_empty())
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
