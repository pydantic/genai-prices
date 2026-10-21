use std::collections::BTreeSet;

use serde_json::{Map, Value};

use crate::calculator::{Calculator, non_empty};
use crate::decode::type_name;
use crate::error::{Error, ErrorKind, Result, validate_number};
use crate::matching::{MatchLogic, Subject, find_model, find_provider};
use crate::model::{PathStep, UsageExtractor};
use crate::request::{Body, ExtractRequest, ExtractedUsage};
use crate::usage::Usage;

impl Calculator {
    /// Extracts usage and the model from a response body.
    ///
    /// # Errors
    ///
    /// Returns an [`ErrorKind::ProviderNotFound`] or [`ErrorKind::ExtractorNotFound`] error if the request
    /// selects no extractor, and an [`ErrorKind::InvalidResponse`] error if the body does not have the
    /// extractor's shape.
    pub fn extract_usage(&self, request: &ExtractRequest<'_>) -> Result<ExtractedUsage> {
        let provider_id = non_empty(request.provider_id.map(str::trim));
        let provider_api_url = non_empty(request.provider_api_url);
        match (provider_id, provider_api_url) {
            (None, None) => {
                return Err(Error::new(ErrorKind::ProviderNotFound, "provider ID or provider API URL is required"));
            }
            (Some(_), Some(_)) => {
                return Err(Error::new(
                    ErrorKind::InvalidUsage,
                    "provider ID and provider API URL are mutually exclusive",
                ));
            }
            _ => {}
        }
        let selected = find_provider(&self.providers, "", provider_id, provider_api_url)?.ok_or_else(|| {
            Error::new(
                ErrorKind::ProviderNotFound,
                format!(
                    "provider_id={:?} provider_api_url={:?}",
                    provider_id.unwrap_or_default(),
                    provider_api_url.unwrap_or_default(),
                ),
            )
        })?;
        let provider = &self.providers[selected];
        if provider.extractors.is_empty() {
            return Err(Error::new(
                ErrorKind::ExtractorNotFound,
                format!("no extraction logic for provider {:?}", provider.id),
            ));
        }
        let flavor = non_empty(request.api_flavor).unwrap_or("default");
        let extractor =
            provider.extractors.iter().find(|extractor| extractor.api_flavor == flavor).ok_or_else(|| {
                let flavors: Vec<&str> =
                    provider.extractors.iter().map(|extractor| extractor.api_flavor.as_str()).collect();
                Error::new(
                    ErrorKind::ExtractorNotFound,
                    format!(
                        "unknown API flavor {flavor:?} for provider {:?}; allowed values: {}",
                        provider.id,
                        flavors.join(", "),
                    ),
                )
            })?;

        let parsed;
        let response = match request.body {
            Body::Value(value) => value,
            Body::Json(json) => {
                parsed = serde_json::from_slice::<Value>(json).map_err(|error| {
                    Error::new(ErrorKind::InvalidResponse, format!("decode response JSON: {error}")).with_source(error)
                })?;
                &parsed
            }
        };
        let Value::Object(response) = response else {
            return Err(Error::new(
                ErrorKind::InvalidResponse,
                format!("expected response data to be a mapping, got {}", type_name(response)),
            ));
        };
        let mut model =
            extract_path(&extractor.model_path, response, false, &[])?.and_then(Value::as_str).map(str::to_owned);
        let (usage, warnings) = self.extract_mapped_usage(extractor, response)?;

        if model.is_none() && provider.id == "cloudflare" {
            if let Some(model_ref) = provider_api_url.and_then(cloudflare_model_from_url) {
                if let Some(matched) = find_model(&self.providers, selected, &model_ref.to_lowercase())? {
                    model = Some(matched.model.id.clone());
                }
            }
        }
        Ok(ExtractedUsage { usage, model, provider_id: provider.id.clone(), warnings })
    }

    fn extract_mapped_usage(
        &self,
        extractor: &UsageExtractor,
        response: &Map<String, Value>,
    ) -> Result<(Usage, Vec<String>)> {
        let root = extract_path(&extractor.root, response, true, &[])?.expect("required paths are found or fail");
        let Value::Object(root_value) = root else {
            return Err(Error::new(
                ErrorKind::InvalidResponse,
                format!(
                    "expected `{}` value to be a mapping, got {}",
                    dotted_path(&extractor.root, &[]),
                    type_name(root),
                ),
            ));
        };

        let mut usage = Usage::new();
        let mut supported_mappings = 0;
        let mut unsupported_destinations = BTreeSet::new();
        for mapping in &extractor.mappings {
            if !self.registry.is_reported(&mapping.dest) {
                unsupported_destinations.insert(mapping.dest.as_str());
                continue;
            }
            supported_mappings += 1;
            let Some(value) = extract_path(&mapping.path, root_value, mapping.required, &extractor.root)? else {
                continue;
            };
            let Some(number) = value.as_f64() else {
                if mapping.required {
                    return Err(Error::new(
                        ErrorKind::InvalidResponse,
                        format!(
                            "expected `{}` value to be a number, got {}",
                            dotted_path(&extractor.root, &mapping.path),
                            type_name(value),
                        ),
                    ));
                }
                continue;
            };
            validate_number(&mapping.dest, number)?;
            let total = usage.add(&mapping.dest, number);
            validate_number(&mapping.dest, total)?;
        }
        if supported_mappings > 0 && usage.is_empty() {
            return Err(Error::new(
                ErrorKind::InvalidResponse,
                format!("no usage information found at {}", dotted_path(&extractor.root, &[])),
            ));
        }
        let warnings = if unsupported_destinations.is_empty() {
            Vec::new()
        } else {
            let destinations: Vec<&str> = unsupported_destinations.into_iter().collect();
            vec![format!("Unsupported extractor destination for standard extraction: {}", destinations.join(", "))]
        };
        Ok((usage, warnings))
    }
}

/// Extracts usage using the bundled provider data. See [`Calculator::extract_usage`].
///
/// # Errors
///
/// See [`Calculator::extract_usage`].
///
/// # Panics
///
/// See [`Calculator::bundled`].
#[cfg(feature = "bundled")]
pub fn extract_usage(request: &ExtractRequest<'_>) -> Result<ExtractedUsage> {
    Calculator::bundled().extract_usage(request)
}

/// Follows `path` from `data`. A missing value is `Ok(None)` unless `required`, in which case it is an
/// error that names the full path, starting with `prefix`.
fn extract_path<'a>(
    path: &[PathStep],
    data: &'a Map<String, Value>,
    required: bool,
    prefix: &[PathStep],
) -> Result<Option<&'a Value>> {
    let missing =
        |message: String| if required { Err(Error::new(ErrorKind::InvalidResponse, message)) } else { Ok(None) };
    let mut current = None::<&'a Value>;
    for (index, step) in path.iter().enumerate() {
        let parent = || dotted_path(prefix, &path[..index]);
        let traversed = || dotted_path(prefix, &path[..=index]);
        current = Some(match step {
            PathStep::Key(key) => {
                let mapping = match current {
                    None => data,
                    Some(Value::Object(mapping)) => mapping,
                    Some(other) => {
                        return missing(format!(
                            "expected `{}` value to be a mapping, got {}",
                            parent(),
                            type_name(other)
                        ));
                    }
                };
                match mapping.get(key) {
                    Some(value) => value,
                    None => return missing(format!("missing value at `{}`", traversed())),
                }
            }
            PathStep::ArrayMatch { field, matcher, .. } => {
                let items = match current {
                    Some(Value::Array(items)) => items,
                    other => {
                        let found = other.map_or("mapping", type_name);
                        return missing(format!("expected `{}` value to be an array, got {found}", parent()));
                    }
                };
                match find_array_item(items, field, matcher)? {
                    Some(item) => item,
                    None => return missing(format!("unable to find item at `{}`", traversed())),
                }
            }
        });
    }
    Ok(current)
}

/// The first object in `items` whose string `field` satisfies `matcher`.
fn find_array_item<'a>(items: &'a [Value], field: &str, matcher: &MatchLogic) -> Result<Option<&'a Value>> {
    for item in items {
        if let Some(Value::String(text)) = item.get(field) {
            if matcher.matches(&Subject::new(text))? {
                return Ok(Some(item));
            }
        }
    }
    Ok(None)
}

fn dotted_path(prefix: &[PathStep], path: &[PathStep]) -> String {
    let parts: Vec<String> = prefix
        .iter()
        .chain(path)
        .map(|step| match step {
            PathStep::Key(key) => key.clone(),
            PathStep::ArrayMatch { source, .. } => source.to_string(),
        })
        .collect();
    parts.join(".")
}

/// The model reference in a Workers AI URL such as `.../ai/run/@cf/meta/llama-3-8b-instruct`.
fn cloudflare_model_from_url(url: &str) -> Option<&str> {
    let after_scheme = url.split_once("://").map_or(url, |(_, rest)| rest);
    let path = &after_scheme[after_scheme.find('/')?..];
    let path = path.split(['?', '#']).next().unwrap_or_default();
    let (_, model) = path.split_once("/ai/run/")?;
    non_empty(Some(model))
}
