use std::fmt;

use crate::calculator::Calculator;
use crate::error::Result;
use crate::matching::find_provider;
use crate::model::{Model, Provider};

/// A provider in the pricing data, as returned by [`Calculator::providers`] and [`Calculator::find_provider`].
#[derive(Clone, Copy)]
pub struct ProviderInfo<'a>(&'a Provider);

impl<'a> ProviderInfo<'a> {
    /// The provider's ID, e.g. `openai`.
    #[must_use]
    pub fn id(self) -> &'a str {
        &self.0.id
    }

    /// The provider's display name, e.g. `OpenAI`.
    #[must_use]
    pub fn name(self) -> &'a str {
        &self.0.name
    }

    /// The models this provider prices, in data order.
    pub fn models(self) -> impl Iterator<Item = ModelInfo<'a>> {
        self.0.models.iter().map(ModelInfo)
    }

    /// The response shapes [`Calculator::extract_usage`] can read for this provider, e.g. `chat`.
    pub fn api_flavors(self) -> impl Iterator<Item = &'a str> {
        self.0.extractors.iter().map(|extractor| extractor.api_flavor.as_str())
    }
}

/// A model in the pricing data, as returned by [`ProviderInfo::models`].
#[derive(Clone, Copy)]
pub struct ModelInfo<'a>(&'a Model);

impl<'a> ModelInfo<'a> {
    /// The model's ID, e.g. `gpt-5`.
    #[must_use]
    pub fn id(self) -> &'a str {
        &self.0.id
    }

    /// The model's display name, if the data has one.
    #[must_use]
    pub fn name(self) -> Option<&'a str> {
        self.0.name.as_deref()
    }

    /// The model's context window in tokens, if the data has one.
    #[must_use]
    pub fn context_window(self) -> Option<u64> {
        self.0.context_window
    }
}

impl fmt::Debug for ProviderInfo<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ProviderInfo").field("id", &self.id()).finish_non_exhaustive()
    }
}

impl fmt::Debug for ModelInfo<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ModelInfo").field("id", &self.id()).finish_non_exhaustive()
    }
}

impl Calculator {
    /// Lists every provider in the pricing data, in data order.
    pub fn providers(&self) -> impl Iterator<Item = ProviderInfo<'_>> {
        self.providers.iter().map(ProviderInfo)
    }

    /// Finds a provider by ID or alias, then by API URL, as a [`PriceRequest`](crate::PriceRequest) selects one.
    ///
    /// # Errors
    ///
    /// Returns an [`ErrorKind::Match`](crate::ErrorKind::Match) error if a regular expression in the data
    /// exceeds its backtracking limit.
    pub fn find_provider(
        &self,
        provider_id: Option<&str>,
        provider_api_url: Option<&str>,
    ) -> Result<Option<ProviderInfo<'_>>> {
        let selected = find_provider(&self.providers, "", provider_id, provider_api_url)?;
        Ok(selected.map(|index| ProviderInfo(&self.providers[index])))
    }
}
