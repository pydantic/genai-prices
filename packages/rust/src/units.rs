//! The unit registry: how usage keys relate to each other and to price keys.
//!
//! Each unit is described by a set of dimensions. A unit is an *ancestor* of another when its dimensions
//! are a subset of the other's (`input_tokens` is an ancestor of `cache_read_tokens`), and the *join* of
//! two compatible units is the unit with the union of their dimensions. Prices are charged on *leaf*
//! values: what remains of a unit's usage after subtracting its more specific priced descendants.

use std::collections::HashMap;
use std::fmt::Write as _;
use std::sync::LazyLock;

use crate::data_units::BUNDLED_UNITS;
use crate::error::{Error, Result, validate_number};
use crate::model::{ModelPrice, PriceValue};
use crate::usage::{Usage, UsageKey};

const REQUESTS: &str = "requests";

/// One registered unit, as generated from `prices/units.yml`.
#[derive(Debug)]
pub(crate) struct UnitDef {
    pub(crate) usage_key: &'static str,
    pub(crate) price_key: &'static str,
    pub(crate) per: f64,
    /// Sorted by dimension name.
    pub(crate) dimensions: &'static [(&'static str, &'static str)],
}

impl UnitDef {
    pub(crate) fn dimension(&self, name: &str) -> Option<&'static str> {
        self.dimensions.iter().find(|(key, _)| *key == name).map(|(_, value)| *value)
    }

    /// Whether every dimension of `self` is also a dimension of `descendant`.
    fn is_subset_of(&self, descendant: &UnitDef) -> bool {
        self.dimensions.iter().all(|(key, value)| descendant.dimension(key) == Some(value))
    }

    /// Whether no dimension is set to different values by `self` and `other`.
    fn is_compatible(&self, other: &UnitDef) -> bool {
        self.dimensions.iter().all(|(key, value)| other.dimension(key).is_none_or(|other| other == *value))
    }
}

/// An index into [`Registry::units`].
pub(crate) type UnitId = usize;

#[derive(Debug)]
pub(crate) struct Registry {
    units: &'static [UnitDef],
    by_usage_key: HashMap<&'static str, UnitId>,
    by_price_key: HashMap<&'static str, UnitId>,
    by_dimensions: HashMap<Vec<(&'static str, &'static str)>, UnitId>,
    /// `ancestors[unit][candidate]` is true when `candidate` is a strict ancestor of `unit`.
    ancestors: Vec<Vec<bool>>,
}

pub(crate) static BUNDLED_REGISTRY: LazyLock<Registry> = LazyLock::new(|| Registry::new(BUNDLED_UNITS));

impl Registry {
    fn new(units: &'static [UnitDef]) -> Self {
        let ancestors = units
            .iter()
            .enumerate()
            .map(|(unit_id, unit)| {
                units.iter().enumerate().map(|(id, candidate)| id != unit_id && candidate.is_subset_of(unit)).collect()
            })
            .collect();
        Self {
            units,
            by_usage_key: units.iter().enumerate().map(|(id, unit)| (unit.usage_key, id)).collect(),
            by_price_key: units.iter().enumerate().map(|(id, unit)| (unit.price_key, id)).collect(),
            by_dimensions: units.iter().enumerate().map(|(id, unit)| (unit.dimensions.to_vec(), id)).collect(),
            ancestors,
        }
    }

    pub(crate) fn unit(&self, id: UnitId) -> &'static UnitDef {
        &self.units[id]
    }

    pub(crate) fn by_usage_key(&self, key: &str) -> Option<UnitId> {
        self.by_usage_key.get(key).copied()
    }

    pub(crate) fn by_price_key(&self, key: &str) -> Option<UnitId> {
        self.by_price_key.get(key).copied()
    }

    /// Whether `key` is a registered unit that providers report, as opposed to `requests`, which is
    /// implied by every call.
    pub(crate) fn is_reported(&self, key: &str) -> bool {
        key != REQUESTS && self.by_usage_key.contains_key(key)
    }

    fn is_ancestor(&self, ancestor: UnitId, of: UnitId) -> bool {
        self.ancestors[of][ancestor]
    }

    fn comparable(&self, left: UnitId, right: UnitId) -> bool {
        left == right || self.is_ancestor(left, right) || self.is_ancestor(right, left)
    }

    /// The registered unit with the union of the dimensions of two compatible units, if any.
    fn join(&self, left: UnitId, right: UnitId) -> Option<UnitId> {
        let (left, right) = (self.unit(left), self.unit(right));
        debug_assert!(left.is_compatible(right), "{} and {} have no join", left.usage_key, right.usage_key);
        let mut dimensions = left.dimensions.to_vec();
        for &(key, value) in right.dimensions {
            if left.dimension(key).is_none() {
                dimensions.push((key, value));
            }
        }
        dimensions.sort_unstable();
        self.by_dimensions.get(&dimensions).copied()
    }
}

/// Checks that a set of prices covers the ancestors and joins of every priced unit.
pub(crate) fn validate_model_price(prices: &ModelPrice, registry: &Registry) -> Result<(), String> {
    let mut priced = Vec::with_capacity(prices.len());
    for (key, price) in prices {
        if let Some(id) = registry.by_price_key(key) {
            price.validate(key)?;
            priced.push(id);
        }
    }
    for &unit in &priced {
        for ancestor in (0..registry.units.len()).filter(|&candidate| registry.is_ancestor(candidate, unit)) {
            if !priced.contains(&ancestor) {
                return Err(format!(
                    "missing ancestor price key {} for {}",
                    registry.unit(ancestor).price_key,
                    registry.unit(unit).price_key,
                ));
            }
        }
    }
    for (index, &left) in priced.iter().enumerate() {
        for &right in &priced[index + 1..] {
            if !registry.unit(left).is_compatible(registry.unit(right)) {
                continue;
            }
            let (left_key, right_key) = (registry.unit(left).price_key, registry.unit(right).price_key);
            let Some(join) = registry.join(left, right) else {
                return Err(format!("missing registered join unit for {left_key} and {right_key}"));
            };
            if !priced.contains(&join) {
                let join_key = registry.unit(join).price_key;
                return Err(format!("missing join price key {join_key} for {left_key} and {right_key}"));
            }
        }
    }
    Ok(())
}

/// Returns the usage value for `unit`, inferring zero only when no reported usage implies otherwise.
pub(crate) fn usage_value(usage: &Usage, unit: UnitId, registry: &Registry) -> Result<f64> {
    let key = registry.unit(unit).usage_key;
    if !registry.is_reported(key) {
        return Err(Error::InvalidUsage(format!("unsupported usage key for standard pricing: {key}")));
    }
    if let Some(&value) = usage.get(key) {
        validate_number(key, value)?;
        return Ok(value);
    }

    let mut positive = Vec::new();
    for (reported_key, &value) in usage {
        let reported_key = reported_key.as_str();
        let Some(reported) = registry.by_usage_key(reported_key).filter(|_| registry.is_reported(reported_key)) else {
            continue;
        };
        validate_number(reported_key, value)?;
        if value <= 0.0 {
            continue;
        }
        positive.push(reported);
        if registry.is_ancestor(unit, reported) {
            return Err(Error::InvalidUsage(format!(
                "missing usage value for {key} with positive reported descendant {reported_key}"
            )));
        }
    }
    for (index, &left) in positive.iter().enumerate() {
        for &right in &positive[index + 1..] {
            if !registry.unit(left).is_compatible(registry.unit(right)) || registry.comparable(left, right) {
                continue;
            }
            if registry.join(left, right) == Some(unit) {
                return Err(Error::InvalidUsage(format!(
                    "missing usage value for {key} with positive reported overlap {} and {}",
                    registry.unit(left).usage_key,
                    registry.unit(right).usage_key,
                )));
            }
        }
    }
    Ok(0.0)
}

/// Decomposes usage into leaf values for the given priced units, most specific first.
fn leaf_values(priced: &[UnitId], usage: &Usage, registry: &Registry) -> Result<HashMap<UnitId, f64>> {
    let mut units = priced.to_vec();
    units.sort_by(|&left, &right| {
        let (left, right) = (registry.unit(left), registry.unit(right));
        right.dimensions.len().cmp(&left.dimensions.len()).then_with(|| left.usage_key.cmp(right.usage_key))
    });
    units.dedup();

    let mut leaves = HashMap::with_capacity(units.len());
    for &unit in &units {
        let value = usage_value(usage, unit, registry)?;
        // Descendants have strictly more dimensions, so they were computed earlier in this loop.
        let descendant_total: f64 = units
            .iter()
            .filter(|&&descendant| descendant != unit && registry.unit(unit).is_subset_of(registry.unit(descendant)))
            .map(|descendant| leaves[descendant])
            .sum();
        let mut leaf = value - descendant_total;
        #[allow(clippy::cast_precision_loss)] // a handful of units
        let tolerance = f64::EPSILON * 1f64.max(value.abs()).max(descendant_total.abs()) * (units.len() + 1) as f64;
        if leaf < 0.0 && leaf.abs() <= tolerance {
            leaf = 0.0;
        }
        if leaf < 0.0 {
            return Err(negative_leaf_error(unit, &units, usage, value, leaf, registry));
        }
        leaves.insert(unit, leaf);
    }
    Ok(leaves)
}

fn negative_leaf_error(
    unit: UnitId,
    priced: &[UnitId],
    usage: &Usage,
    unit_value: f64,
    leaf_value: f64,
    registry: &Registry,
) -> Error {
    let unit_key = registry.unit(unit).usage_key;
    let descendants: Vec<(&str, f64)> = priced
        .iter()
        .filter(|&&descendant| descendant != unit && registry.unit(unit).is_subset_of(registry.unit(descendant)))
        .filter_map(|&descendant| {
            let value = usage_value(usage, descendant, registry).ok().filter(|&value| value > 0.0)?;
            Some((registry.unit(descendant).usage_key, value))
        })
        .collect();
    if let Some((key, value)) = descendants.iter().find(|(_, value)| *value > unit_value) {
        return Error::InvalidUsage(format!("{key} ({value}) cannot exceed {unit_key} ({unit_value})"));
    }
    let mut keys = String::new();
    for (index, (key, _)) in descendants.iter().enumerate() {
        let separator = if index == 0 { "" } else { ", " };
        let _ = write!(keys, "{separator}{key}");
    }
    Error::InvalidUsage(format!(
        "more-specific usage for {keys} totals {}, which exceeds {unit_key} ({unit_value})",
        unit_value - leaf_value,
    ))
}

/// Input, output and total prices in US dollars.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub(crate) struct Prices {
    pub(crate) input: f64,
    pub(crate) output: f64,
    pub(crate) total: f64,
}

pub(crate) fn calculate_model_price(usage: &Usage, prices: &ModelPrice, registry: &Registry) -> Result<Prices> {
    // `ModelPrice` is a `BTreeMap`, so units are priced in a deterministic order.
    let resolved: Vec<(&PriceValue, UnitId)> =
        prices.iter().filter_map(|(key, price)| Some((price, registry.by_price_key(key)?))).collect();
    let has_tiered = resolved.iter().any(|(price, _)| matches!(price, PriceValue::Tiered { .. }));
    let requests = registry.by_usage_key(REQUESTS);
    let priced: Vec<UnitId> = resolved.iter().map(|&(_, unit)| unit).filter(|&unit| Some(unit) != requests).collect();

    let total_input_tokens = if has_tiered {
        let input_tokens = registry
            .by_usage_key(UsageKey::INPUT_TOKENS.as_str())
            .ok_or_else(|| Error::InvalidUsage("unknown unit usage key input_tokens".into()))?;
        usage_value(usage, input_tokens, registry)?
    } else {
        0.0
    };
    let leaves = leaf_values(&priced, usage, registry)?;

    let mut result = Prices::default();
    for (price, unit) in resolved {
        let count = if Some(unit) == requests { 1.0 } else { leaves[&unit] };
        let rate = match price {
            PriceValue::Flat(rate) => *rate,
            PriceValue::Tiered { base, tiers } if count > 0.0 => {
                tiers.iter().rev().find(|tier| total_input_tokens > tier.start).map_or(*base, |tier| tier.price)
            }
            PriceValue::Tiered { base, .. } => *base,
        };
        let definition = registry.unit(unit);
        let unit_price = rate * count / definition.per;
        validate_number("calculated unit price", unit_price)?;
        match definition.dimension("direction") {
            Some("input") => {
                result.input += unit_price;
                validate_number("calculated input price", result.input)?;
            }
            Some("output") => {
                result.output += unit_price;
                validate_number("calculated output price", result.output)?;
            }
            _ => {
                result.total += unit_price;
                validate_number("calculated total price", result.total)?;
            }
        }
    }
    result.total += result.input + result.output;
    validate_number("calculated total price", result.total)?;
    Ok(result)
}

/// Warnings for usage and price keys that this release does not know how to price.
pub(crate) fn calculation_warnings(usage: &Usage, prices: &ModelPrice, registry: &Registry) -> Vec<String> {
    let usage_keys: Vec<&str> = usage.keys().map(UsageKey::as_str).filter(|key| !registry.is_reported(key)).collect();
    let price_keys: Vec<&str> =
        prices.keys().map(String::as_str).filter(|key| registry.by_price_key(key).is_none()).collect();
    let mut warnings = Vec::new();
    if !usage_keys.is_empty() {
        warnings.push(format!("Unsupported usage key for standard pricing: {}", usage_keys.join(", ")));
    }
    if !price_keys.is_empty() {
        warnings.push(format!("Unsupported price key for standard pricing: {}", price_keys.join(", ")));
    }
    warnings
}
