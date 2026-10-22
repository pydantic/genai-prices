//! Decoding and validating a v2 provider-data payload.
//!
//! The payload is parsed into a [`Value`] first, which keeps the last of any duplicated keys (as Python
//! and JavaScript do), and then walked by hand so that every malformed shape is rejected with context
//! rather than silently defaulted.

use std::collections::{BTreeMap, HashSet};

use fancy_regex::Regex;
use serde_json::{Map, Value};

use crate::error::{Error, ErrorKind};
use crate::matching::MatchLogic;
use crate::model::{
    ConditionalPrice, Constraint, ExtractPath, Model, ModelPrice, ModelPrices, PathStep, PriceValue, PriceVariant,
    Provider, Tier, UsageExtractor, UsageExtractorMapping,
};
use crate::time::{parse_date, parse_time_of_day};
use crate::units::{Registry, validate_model_price};

type DecodeResult<T> = Result<T, String>;

pub(crate) fn decode_providers(data: &[u8], registry: &Registry) -> crate::Result<Vec<Provider>> {
    let value: Value = serde_json::from_slice(data)
        .map_err(|error| Error::new(ErrorKind::InvalidData, error.to_string()).with_source(error))?;
    decode_provider_array(&value, registry).map_err(|message| Error::new(ErrorKind::InvalidData, message))
}

fn decode_provider_array(value: &Value, registry: &Registry) -> DecodeResult<Vec<Provider>> {
    let Value::Array(items) = value else {
        return Err(format!("expected a provider array, got {}", type_name(value)));
    };
    let providers = items.iter().map(|item| decode_provider(item, registry)).collect::<DecodeResult<Vec<_>>>()?;
    let mut ids = HashSet::with_capacity(providers.len());
    for provider in &providers {
        if !ids.insert(provider.id.as_str()) {
            return Err(format!("duplicate provider ID {:?}", provider.id));
        }
    }
    Ok(providers)
}

/// The fields of a JSON object. Like a struct in Go or a dataclass with defaults, `null` decodes as an
/// object with no fields, and fields that are `null` read as absent unless fetched with [`Fields::raw`].
#[derive(Clone, Copy)]
struct Fields<'a>(Option<&'a Map<String, Value>>);

impl<'a> Fields<'a> {
    fn of(value: &'a Value, what: &str) -> DecodeResult<Self> {
        match value {
            Value::Null => Ok(Self(None)),
            Value::Object(map) => Ok(Self(Some(map))),
            other => Err(format!("{what} must be an object, got {}", type_name(other))),
        }
    }

    /// The field, including an explicit `null`.
    fn raw(self, key: &str) -> Option<&'a Value> {
        self.0?.get(key)
    }

    fn get(self, key: &str) -> Option<&'a Value> {
        self.raw(key).filter(|value| !value.is_null())
    }

    fn string(self, key: &str) -> DecodeResult<Option<&'a str>> {
        match self.get(key) {
            None => Ok(None),
            Some(Value::String(value)) => Ok(Some(value)),
            Some(other) => Err(format!("{key} must be a string, got {}", type_name(other))),
        }
    }

    fn array(self, key: &str) -> DecodeResult<&'a [Value]> {
        match self.get(key) {
            None => Ok(&[]),
            Some(Value::Array(items)) => Ok(items),
            Some(other) => Err(format!("{key} must be an array, got {}", type_name(other))),
        }
    }

    fn boolean(self, key: &str) -> DecodeResult<bool> {
        match self.get(key) {
            None => Ok(false),
            Some(Value::Bool(value)) => Ok(*value),
            Some(other) => Err(format!("{key} must be a boolean, got {}", type_name(other))),
        }
    }
}

fn decode_provider(value: &Value, registry: &Registry) -> DecodeResult<Provider> {
    let fields = Fields::of(value, "provider")?;
    let id = fields.string("id")?.unwrap_or_default();
    let name = fields.string("name")?.unwrap_or_default();
    let api_pattern = fields.string("api_pattern")?.unwrap_or_default();
    if id.is_empty() || name.is_empty() || api_pattern.is_empty() {
        return Err("provider id, name, and api_pattern are required".into());
    }
    if id != id.trim().to_lowercase() {
        return Err(format!("provider ID {id:?} must be lowercase without surrounding whitespace"));
    }
    let context = |error: String| format!("provider {id:?} {error}");
    let api_regex =
        compile_regex(&format!("^(?:{api_pattern})")).map_err(|error| context(format!("API pattern: {error}")))?;
    let model_match =
        optional_match(fields.get("model_match")).map_err(|error| context(format!("match logic: {error}")))?;
    let provider_match =
        optional_match(fields.get("provider_match")).map_err(|error| context(format!("match logic: {error}")))?;
    let extractors = fields
        .array("extractors")
        .map_err(context)?
        .iter()
        .map(decode_extractor)
        .collect::<DecodeResult<_>>()
        .map_err(context)?;
    let fallback_model_providers = fields
        .array("fallback_model_providers")
        .map_err(context)?
        .iter()
        .map(|value| {
            value.as_str().map(str::to_owned).ok_or_else(|| "fallback_model_providers must be strings".to_owned())
        })
        .collect::<DecodeResult<_>>()
        .map_err(context)?;

    let mut models = Vec::new();
    let mut model_ids = HashSet::new();
    for value in fields.array("models").map_err(context)? {
        let model = decode_model(value, registry).map_err(context)?;
        if !model_ids.insert(model.id.clone()) {
            return Err(context(format!("has duplicate model ID {:?}", model.id)));
        }
        models.push(model);
    }

    Ok(Provider {
        id: id.to_owned(),
        api_regex,
        model_match,
        provider_match,
        extractors,
        fallback_model_providers,
        models,
    })
}

fn decode_model(value: &Value, registry: &Registry) -> DecodeResult<Model> {
    let fields = Fields::of(value, "model")?;
    let id = fields.string("id")?.unwrap_or_default();
    if id.is_empty() {
        return Err("has a model without an ID".into());
    }
    let context = |error: String| format!("model {id:?} {error}");
    let match_logic = decode_match(fields.raw("match").unwrap_or(&Value::Null))
        .map_err(|error| context(format!("match logic: {error}")))?;
    let prices = match fields.raw("prices") {
        None => ModelPrices::Direct(ModelPrice::new()),
        Some(Value::Array(items)) => {
            let conditional =
                items.iter().map(decode_conditional_price).collect::<DecodeResult<Vec<_>>>().map_err(context)?;
            if conditional.is_empty() {
                return Err(context("has no conditional prices".into()));
            }
            if conditional.iter().filter(|price| price.constraint.is_none()).count() != 1 {
                return Err(context("must have exactly one unconstrained price".into()));
            }
            ModelPrices::Conditional(conditional)
        }
        Some(other) => ModelPrices::Direct(decode_model_price(other).map_err(context)?),
    };
    match &prices {
        ModelPrices::Direct(prices) => validate_model_price(prices, registry),
        ModelPrices::Conditional(conditional) => {
            conditional.iter().try_for_each(|price| validate_model_price(&price.prices, registry))
        }
    }
    .map_err(|error| context(format!("prices: {error}")))?;
    let price_variants = fields
        .array("price_variants")
        .map_err(context)?
        .iter()
        .map(decode_price_variant)
        .collect::<DecodeResult<_>>()
        .map_err(|error| context(format!("price variant: {error}")))?;
    Ok(Model { id: id.to_owned(), match_logic, prices, price_variants })
}

fn decode_model_price(value: &Value) -> DecodeResult<ModelPrice> {
    let Value::Object(map) = value else {
        return Err(format!("prices must be an object or array, got {}", type_name(value)));
    };
    map.iter().map(|(key, value)| Ok((key.clone(), decode_price_value(key, value)?))).collect()
}

fn decode_price_value(key: &str, value: &Value) -> DecodeResult<PriceValue> {
    match value {
        Value::Number(number) => {
            let price = number.as_f64().ok_or_else(|| format!("{key} is not representable as a float"))?;
            Ok(PriceValue::Flat(price))
        }
        Value::Object(_) => {
            let fields = Fields::of(value, key)?;
            let (Some(base), Some(tiers)) = (fields.get("base"), fields.get("tiers")) else {
                return Err(format!("{key} tiered price must contain base and tiers"));
            };
            let base = base.as_f64().ok_or_else(|| format!("{key} base must be a number"))?;
            let Value::Array(tiers) = tiers else {
                return Err(format!("{key} tiers must be an array"));
            };
            let mut tiers = tiers.iter().map(|tier| decode_tier(key, tier)).collect::<DecodeResult<Vec<_>>>()?;
            tiers.sort_by(|left, right| left.start.total_cmp(&right.start));
            Ok(PriceValue::Tiered { base, tiers })
        }
        other => Err(format!("{key} must be a number or tiered-price object, got {}", type_name(other))),
    }
}

fn decode_tier(key: &str, value: &Value) -> DecodeResult<Tier> {
    let fields = Fields::of(value, "tier")?;
    let (Some(start), Some(price)) = (fields.get("start"), fields.get("price")) else {
        return Err(format!("{key} tier must contain start and price"));
    };
    let start = start.as_i64().ok_or_else(|| format!("{key} tier start must be an integer"))?;
    let price = price.as_f64().ok_or_else(|| format!("{key} tier price must be a number"))?;
    #[allow(clippy::cast_precision_loss)] // token counts are far below 2^53
    Ok(Tier { start: start as f64, price })
}

fn decode_conditional_price(value: &Value) -> DecodeResult<ConditionalPrice> {
    let fields = Fields::of(value, "conditional price")?;
    let prices = fields.get("prices").ok_or("conditional price must contain prices")?;
    let constraint = match fields.raw("constraint") {
        None => None,
        Some(Value::Null) => return Err("constraint must be an object".into()),
        Some(constraint) => Some(decode_constraint(constraint)?),
    };
    Ok(ConditionalPrice { constraint, prices: decode_model_price(prices)? })
}

fn decode_constraint(value: &Value) -> DecodeResult<Constraint> {
    let fields = Fields::of(value, "price constraint")?;
    for key in fields.0.into_iter().flat_map(Map::keys) {
        if !matches!(key.as_str(), "start_date" | "start_time" | "end_time" | "type") {
            return Err(format!("unknown price constraint field {key:?}"));
        }
    }
    let start_date = fields.string("start_date")?.unwrap_or_default();
    let start_time = fields.string("start_time")?.unwrap_or_default();
    let end_time = fields.string("end_time")?.unwrap_or_default();
    if fields.raw("type").is_some() {
        let kind = fields.string("type")?.ok_or("price constraint type must be a string")?;
        let start_date_shape =
            kind == "start_date" && !start_date.is_empty() && start_time.is_empty() && end_time.is_empty();
        let time_of_day_shape =
            kind == "time_of_date" && start_date.is_empty() && !start_time.is_empty() && !end_time.is_empty();
        if !start_date_shape && !time_of_day_shape {
            return Err("price constraint type does not match its fields".into());
        }
    }
    match (start_date.is_empty(), start_time.is_empty(), end_time.is_empty()) {
        (false, true, true) => Ok(Constraint::StartDate(parse_date(start_date)?)),
        (true, false, false) => {
            Ok(Constraint::TimeOfDay { start: parse_time_of_day(start_time)?, end: parse_time_of_day(end_time)? })
        }
        _ => Err("expected a start-date or time-of-day price constraint".into()),
    }
}

fn decode_price_variant(value: &Value) -> DecodeResult<PriceVariant> {
    let fields = Fields::of(value, "price variant")?;
    let when = match fields.get("when") {
        None => BTreeMap::new(),
        Some(Value::Object(map)) => map
            .iter()
            .map(|(key, value)| match value {
                Value::String(text) => Ok((key.clone(), text.clone())),
                _ => Err("price variant when values must be strings".to_owned()),
            })
            .collect::<DecodeResult<_>>()?,
        Some(other) => return Err(format!("price variant when must be an object, got {}", type_name(other))),
    };
    let prices = match fields.get("prices") {
        Some(Value::Object(map)) => map
            .iter()
            .filter(|(_, value)| !value.is_null())
            .map(|(key, value)| Ok((key.clone(), decode_price_value(key, value)?)))
            .collect::<DecodeResult<ModelPrice>>()?,
        Some(other) => return Err(format!("price variant prices must be an object, got {}", type_name(other))),
        None => return Err("price variant must contain when and prices".into()),
    };
    if when.is_empty() {
        return Err("price variant must contain when and prices".into());
    }
    prices.iter().try_for_each(|(key, price)| price.validate(key))?;
    let constraint = fields.get("constraint").map(decode_constraint).transpose()?;
    Ok(PriceVariant { when, prices, constraint })
}

fn optional_match(value: Option<&Value>) -> DecodeResult<Option<MatchLogic>> {
    value.map(decode_match).transpose()
}

fn decode_match(value: &Value) -> DecodeResult<MatchLogic> {
    let fields = Fields::of(value, "match logic")?;
    let mut operations = Vec::with_capacity(1);
    for operation in ["and", "or", "contains", "ends_with", "equals", "regex", "starts_with"] {
        if let Some(argument) = fields.get(operation) {
            operations.push((operation, argument));
        }
    }
    let [(operation, argument)] = operations[..] else {
        return Err("match logic must contain exactly one operation".into());
    };
    let literal = |rule: fn(String) -> MatchLogic| match argument {
        Value::String(value) => Ok(rule(value.to_lowercase())),
        other => Err(format!("{operation} must be a string, got {}", type_name(other))),
    };
    match operation {
        "and" | "or" => {
            let Value::Array(rules) = argument else {
                return Err(format!("{operation} must be an array, got {}", type_name(argument)));
            };
            let rules = rules.iter().map(decode_match).collect::<DecodeResult<Vec<_>>>()?;
            Ok(if operation == "and" { MatchLogic::And(rules) } else { MatchLogic::Or(rules) })
        }
        "regex" => match argument {
            Value::String(pattern) => Ok(MatchLogic::Regex(Box::new(compile_regex(pattern)?))),
            other => Err(format!("regex must be a string, got {}", type_name(other))),
        },
        "contains" => literal(MatchLogic::Contains),
        "ends_with" => literal(MatchLogic::EndsWith),
        "equals" => literal(MatchLogic::Equals),
        _ => literal(MatchLogic::StartsWith),
    }
}

fn compile_regex(pattern: &str) -> DecodeResult<Regex> {
    Regex::new(pattern).map_err(|error| format!("compile regex {pattern:?}: {error}"))
}

fn decode_extractor(value: &Value) -> DecodeResult<UsageExtractor> {
    let fields = Fields::of(value, "extractor")?;
    let api_flavor = match fields.string("api_flavor")? {
        None | Some("") => "default".to_owned(),
        Some(flavor) => flavor.to_owned(),
    };
    let context = |what: &str, error: String| format!("extractor {api_flavor:?} {what}: {error}");
    let root = decode_path(fields.raw("root")).map_err(|error| context("root", error))?;
    let model_path = match fields.raw("model_path") {
        None => vec![PathStep::Key("model".into())],
        raw => decode_path(raw).map_err(|error| context("model path", error))?,
    };
    let mappings = fields
        .array("mappings")
        .map_err(|error| context("mappings", error))?
        .iter()
        .enumerate()
        .map(|(index, value)| decode_mapping(value).map_err(|error| context(&format!("mapping {index}"), error)))
        .collect::<DecodeResult<_>>()?;
    Ok(UsageExtractor { api_flavor, root, model_path, mappings })
}

fn decode_mapping(value: &Value) -> DecodeResult<UsageExtractorMapping> {
    let fields = Fields::of(value, "mapping")?;
    Ok(UsageExtractorMapping {
        path: decode_path(fields.raw("path"))?,
        dest: fields.string("dest")?.unwrap_or_default().to_owned(),
        required: fields.boolean("required")?,
    })
}

fn decode_path(value: Option<&Value>) -> DecodeResult<ExtractPath> {
    let steps = match value {
        Some(Value::String(key)) => vec![PathStep::Key(key.clone())],
        Some(Value::Array(items)) => items.iter().map(decode_path_step).collect::<DecodeResult<Vec<_>>>()?,
        _ => return Err("extract path must be a string or array".into()),
    };
    match steps.last() {
        Some(PathStep::Key(_)) => Ok(steps),
        _ => Err("path must end with a string".into()),
    }
}

fn decode_path_step(value: &Value) -> DecodeResult<PathStep> {
    if let Value::String(key) = value {
        return Ok(PathStep::Key(key.clone()));
    }
    let fields = Fields::of(value, "path step")?;
    let field = fields.string("field")?.unwrap_or_default();
    if fields.string("type")? != Some("array-match") || field.is_empty() {
        return Err("invalid array-match step".into());
    }
    let matcher = decode_match(fields.raw("match").unwrap_or(&Value::Null))?;
    Ok(PathStep::ArrayMatch { field: field.to_owned(), matcher, source: value.clone() })
}

pub(crate) fn type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "boolean",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "mapping",
    }
}
