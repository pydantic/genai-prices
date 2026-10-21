//! The unit registry: how usage keys relate to each other and to price keys.
//!
//! Each unit is described by a set of dimensions. A unit is an *ancestor* of another when its dimensions
//! are a subset of the other's (`input_tokens` is an ancestor of `cache_read_tokens`), and the *join* of
//! two compatible units is the unit with the union of their dimensions. Prices are charged on *leaf*
//! values: what remains of a unit's usage after subtracting its more specific priced descendants.
//!
//! Everything a calculation needs about units is precomputed here, and per-unit state during a calculation
//! lives in [`UnitMap`]s on the stack, so pricing a request does not allocate.

use std::collections::HashMap;
use std::fmt::Write as _;
use std::sync::LazyLock;

use crate::data_units::{BUNDLED_UNITS, UNIT_COUNT};
use crate::error::{Error, ErrorKind, Result, validate_number};
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

/// An index into the registered units.
pub(crate) type UnitId = usize;

/// A value for each registered unit, stored inline.
pub(crate) type UnitMap<T> = [T; UNIT_COUNT];

#[derive(Debug)]
pub(crate) struct Registry {
    units: &'static UnitMap<UnitDef>,
    by_usage_key: HashMap<&'static str, UnitId>,
    by_price_key: HashMap<&'static str, UnitId>,
    requests: Option<UnitId>,
    input_tokens: Option<UnitId>,
    /// `ancestors[unit][candidate]` is true when `candidate` is a strict ancestor of `unit`.
    ancestors: Vec<UnitMap<bool>>,
    /// `joins[left][right]` is the registered join of two compatible units.
    joins: Vec<UnitMap<Option<UnitId>>>,
    /// Units ordered by price key, the order prices are summed in (as in the other engines).
    price_order: UnitMap<UnitId>,
    /// Units ordered most specific first, then by usage key: the order usage is decomposed in.
    decomposition_order: UnitMap<UnitId>,
}

pub(crate) static BUNDLED_REGISTRY: LazyLock<Registry> = LazyLock::new(|| Registry::new(&BUNDLED_UNITS));

/// The static string of a registered usage key, so keys built from strings need not allocate.
pub(crate) fn registered_usage_key(key: &str) -> Option<&'static str> {
    let registry = &*BUNDLED_REGISTRY;
    registry.by_usage_key(key).map(|id| registry.unit(id).usage_key)
}

impl Registry {
    fn new(units: &'static UnitMap<UnitDef>) -> Self {
        let by_dimensions: HashMap<_, _> = units.iter().enumerate().map(|(id, unit)| (unit.dimensions, id)).collect();
        let ancestors = units
            .iter()
            .enumerate()
            .map(|(unit_id, unit)| std::array::from_fn(|id| id != unit_id && units[id].is_subset_of(unit)))
            .collect();
        let joins = units
            .iter()
            .map(|left| {
                std::array::from_fn(|id| {
                    let right = &units[id];
                    if !left.is_compatible(right) {
                        return None;
                    }
                    let mut dimensions = left.dimensions.to_vec();
                    dimensions.extend(right.dimensions.iter().filter(|(key, _)| left.dimension(key).is_none()));
                    dimensions.sort_unstable();
                    by_dimensions.get(dimensions.as_slice()).copied()
                })
            })
            .collect();
        let mut price_order: UnitMap<UnitId> = std::array::from_fn(|id| id);
        price_order.sort_by_key(|&id| units[id].price_key);
        let mut decomposition_order: UnitMap<UnitId> = std::array::from_fn(|id| id);
        decomposition_order.sort_by(|&left, &right| {
            let (left, right) = (&units[left], &units[right]);
            right.dimensions.len().cmp(&left.dimensions.len()).then_with(|| left.usage_key.cmp(right.usage_key))
        });
        let by_usage_key: HashMap<_, _> = units.iter().enumerate().map(|(id, unit)| (unit.usage_key, id)).collect();
        Self {
            units,
            requests: by_usage_key.get(REQUESTS).copied(),
            input_tokens: by_usage_key.get(UsageKey::INPUT_TOKENS.as_str()).copied(),
            by_usage_key,
            by_price_key: units.iter().enumerate().map(|(id, unit)| (unit.price_key, id)).collect(),
            ancestors,
            joins,
            price_order,
            decomposition_order,
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

    fn compatible(&self, left: UnitId, right: UnitId) -> bool {
        self.unit(left).is_compatible(self.unit(right))
    }

    /// The registered unit with the union of the dimensions of two compatible units, if any.
    fn join(&self, left: UnitId, right: UnitId) -> Option<UnitId> {
        self.joins[left][right]
    }
}

/// The registered prices that apply to one calculation, borrowed from the provider data.
#[derive(Clone, Copy)]
pub(crate) struct PriceSet<'a> {
    prices: UnitMap<Option<&'a PriceValue>>,
}

impl<'a> PriceSet<'a> {
    /// The registered prices in `prices`; keys this release does not know are left out.
    pub(crate) fn new(prices: &'a ModelPrice, registry: &Registry) -> Self {
        let mut set = Self { prices: [None; UNIT_COUNT] };
        for (key, price) in prices {
            if let Some(unit) = registry.by_price_key(key) {
                set.prices[unit] = Some(price);
            }
        }
        set
    }

    pub(crate) fn set(&mut self, unit: UnitId, price: &'a PriceValue) {
        self.prices[unit] = Some(price);
    }

    fn contains(&self, unit: UnitId) -> bool {
        self.prices[unit].is_some()
    }

    /// The priced units and their prices, ordered by price key.
    fn iter<'s>(&'s self, registry: &'s Registry) -> impl Iterator<Item = (UnitId, &'a PriceValue)> + 's {
        registry.price_order.iter().filter_map(|&unit| Some((unit, self.prices[unit]?)))
    }
}

/// Checks that a model's prices cover the ancestors and joins of every priced unit.
pub(crate) fn validate_model_price(prices: &ModelPrice, registry: &Registry) -> Result<(), String> {
    validate_price_set(&PriceSet::new(prices, registry), registry)
}

/// Checks that a set of prices covers the ancestors and joins of every priced unit.
pub(crate) fn validate_price_set(prices: &PriceSet<'_>, registry: &Registry) -> Result<(), String> {
    for (unit, price) in prices.iter(registry) {
        price.validate(registry.unit(unit).price_key)?;
    }
    for (unit, _) in prices.iter(registry) {
        for ancestor in (0..UNIT_COUNT).filter(|&candidate| registry.is_ancestor(candidate, unit)) {
            if !prices.contains(ancestor) {
                return Err(format!(
                    "missing ancestor price key {} for {}",
                    registry.unit(ancestor).price_key,
                    registry.unit(unit).price_key,
                ));
            }
        }
    }
    for (index, (left, _)) in prices.iter(registry).enumerate() {
        for (right, _) in prices.iter(registry).skip(index + 1) {
            if !registry.compatible(left, right) {
                continue;
            }
            let (left_key, right_key) = (registry.unit(left).price_key, registry.unit(right).price_key);
            let Some(join) = registry.join(left, right) else {
                return Err(format!("missing registered join unit for {left_key} and {right_key}"));
            };
            if !prices.contains(join) {
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
        return Err(Error::new(ErrorKind::InvalidUsage, format!("unsupported usage key for standard pricing: {key}")));
    }
    if let Some(value) = usage.get(key) {
        validate_number(key, value)?;
        return Ok(value);
    }

    let mut positive: UnitMap<UnitId> = [0; UNIT_COUNT];
    let mut positive_count = 0;
    for (reported_key, value) in usage {
        let reported_key = reported_key.as_str();
        let Some(reported) = registry.by_usage_key(reported_key).filter(|_| registry.is_reported(reported_key)) else {
            continue;
        };
        validate_number(reported_key, value)?;
        if value <= 0.0 {
            continue;
        }
        // Usage keys are unique, so there are at most `UNIT_COUNT` registered ones.
        positive[positive_count] = reported;
        positive_count += 1;
        if registry.is_ancestor(unit, reported) {
            return Err(Error::new(
                ErrorKind::InvalidUsage,
                format!("missing usage value for {key} with positive reported descendant {reported_key}"),
            ));
        }
    }
    let positive = &positive[..positive_count];
    for (index, &left) in positive.iter().enumerate() {
        for &right in &positive[index + 1..] {
            if !registry.compatible(left, right) || registry.comparable(left, right) {
                continue;
            }
            if registry.join(left, right) == Some(unit) {
                return Err(Error::new(
                    ErrorKind::InvalidUsage,
                    format!(
                        "missing usage value for {key} with positive reported overlap {} and {}",
                        registry.unit(left).usage_key,
                        registry.unit(right).usage_key,
                    ),
                ));
            }
        }
    }
    Ok(0.0)
}

/// Decomposes usage into leaf values for the priced units (other than `requests`), most specific first.
fn leaf_values(prices: &PriceSet<'_>, usage: &Usage, registry: &Registry) -> Result<UnitMap<f64>> {
    let priced = |unit: UnitId| prices.contains(unit) && Some(unit) != registry.requests;
    let priced_count = (0..UNIT_COUNT).filter(|&unit| priced(unit)).count();
    let ordered = || registry.decomposition_order.iter().copied().filter(|&unit| priced(unit));

    let mut leaves = [0.0; UNIT_COUNT];
    for unit in ordered() {
        let value = usage_value(usage, unit, registry)?;
        // Descendants have strictly more dimensions, so they were computed earlier in this loop.
        let descendant_total: f64 = ordered()
            .filter(|&descendant| descendant != unit && registry.unit(unit).is_subset_of(registry.unit(descendant)))
            .map(|descendant| leaves[descendant])
            .sum();
        let mut leaf = value - descendant_total;
        #[allow(clippy::cast_precision_loss)] // a handful of units
        let tolerance = f64::EPSILON * 1f64.max(value.abs()).max(descendant_total.abs()) * (priced_count + 1) as f64;
        if leaf < 0.0 && leaf.abs() <= tolerance {
            leaf = 0.0;
        }
        if leaf < 0.0 {
            return Err(negative_leaf_error(unit, ordered(), usage, value, leaf, registry));
        }
        leaves[unit] = leaf;
    }
    Ok(leaves)
}

fn negative_leaf_error(
    unit: UnitId,
    priced: impl Iterator<Item = UnitId>,
    usage: &Usage,
    unit_value: f64,
    leaf_value: f64,
    registry: &Registry,
) -> Error {
    let unit_key = registry.unit(unit).usage_key;
    let descendants: Vec<(&str, f64)> = priced
        .filter(|&descendant| descendant != unit && registry.unit(unit).is_subset_of(registry.unit(descendant)))
        .filter_map(|descendant| {
            let value = usage_value(usage, descendant, registry).ok().filter(|&value| value > 0.0)?;
            Some((registry.unit(descendant).usage_key, value))
        })
        .collect();
    if let Some((key, value)) = descendants.iter().find(|(_, value)| *value > unit_value) {
        return Error::new(ErrorKind::InvalidUsage, format!("{key} ({value}) cannot exceed {unit_key} ({unit_value})"));
    }
    let mut keys = String::new();
    for (index, (key, _)) in descendants.iter().enumerate() {
        let separator = if index == 0 { "" } else { ", " };
        let _ = write!(keys, "{separator}{key}");
    }
    Error::new(
        ErrorKind::InvalidUsage,
        format!(
            "more-specific usage for {keys} totals {}, which exceeds {unit_key} ({unit_value})",
            unit_value - leaf_value,
        ),
    )
}

/// Input, output and total prices in US dollars.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub(crate) struct Prices {
    pub(crate) input: f64,
    pub(crate) output: f64,
    pub(crate) total: f64,
}

pub(crate) fn calculate_model_price(usage: &Usage, prices: &PriceSet<'_>, registry: &Registry) -> Result<Prices> {
    let has_tiered = prices.iter(registry).any(|(_, price)| matches!(price, PriceValue::Tiered { .. }));
    let total_input_tokens = match registry.input_tokens {
        Some(input_tokens) if has_tiered => usage_value(usage, input_tokens, registry)?,
        None if has_tiered => {
            return Err(Error::new(ErrorKind::InvalidUsage, "unknown unit usage key input_tokens"));
        }
        _ => 0.0,
    };
    let leaves = leaf_values(prices, usage, registry)?;

    let mut result = Prices::default();
    for (unit, price) in prices.iter(registry) {
        let count = if Some(unit) == registry.requests { 1.0 } else { leaves[unit] };
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

/// Warnings for usage and price keys that this release does not know how to price. `unknown_price_keys` may
/// repeat keys and be unordered. Nothing is allocated when there is nothing to report.
pub(crate) fn calculation_warnings(
    usage: &Usage,
    mut unknown_price_keys: Vec<&str>,
    registry: &Registry,
) -> Vec<String> {
    let mut warnings = Vec::new();
    let mut usage_keys = usage.keys().map(UsageKey::as_str).filter(|key| !registry.is_reported(key)).peekable();
    if usage_keys.peek().is_some() {
        let usage_keys: Vec<&str> = usage_keys.collect();
        warnings.push(format!("Unsupported usage key for standard pricing: {}", usage_keys.join(", ")));
    }
    if !unknown_price_keys.is_empty() {
        unknown_price_keys.sort_unstable();
        unknown_price_keys.dedup();
        warnings.push(format!("Unsupported price key for standard pricing: {}", unknown_price_keys.join(", ")));
    }
    warnings
}
