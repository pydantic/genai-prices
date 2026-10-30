//! The in-memory form of the v2 provider data.

use std::collections::BTreeMap;

use crate::matching::MatchLogic;
use crate::time::Timestamp;

#[derive(Debug)]
pub(crate) struct Provider {
    pub(crate) id: String,
    pub(crate) name: String,
    pub(crate) api_regex: fancy_regex::Regex,
    pub(crate) model_match: Option<MatchLogic>,
    pub(crate) provider_match: Option<MatchLogic>,
    pub(crate) extractors: Vec<UsageExtractor>,
    pub(crate) fallback_model_providers: Vec<String>,
    pub(crate) models: Vec<Model>,
}

#[derive(Debug)]
pub(crate) struct Model {
    pub(crate) id: String,
    pub(crate) name: Option<String>,
    pub(crate) context_window: Option<u64>,
    pub(crate) match_logic: MatchLogic,
    pub(crate) prices: ModelPrices,
    pub(crate) price_variants: Vec<PriceVariant>,
}

#[derive(Debug)]
pub(crate) enum ModelPrices {
    Direct(ModelPrice),
    /// Never empty, and exactly one entry has no constraint.
    Conditional(Vec<ConditionalPrice>),
}

/// Prices keyed by price key, e.g. `input_mtok`.
pub(crate) type ModelPrice = BTreeMap<String, PriceValue>;

#[derive(Debug, Clone, PartialEq)]
pub(crate) enum PriceValue {
    Flat(f64),
    /// `tiers` is sorted by `start`.
    Tiered {
        base: f64,
        tiers: Vec<Tier>,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct Tier {
    pub(crate) start: f64,
    pub(crate) price: f64,
}

impl PriceValue {
    pub(crate) fn validate(&self, key: &str) -> Result<(), String> {
        let finite = |value: f64| {
            if value.is_finite() && value >= 0.0 {
                Ok(())
            } else {
                Err(format!("{key} must be a finite non-negative number"))
            }
        };
        match self {
            Self::Flat(price) => finite(*price),
            Self::Tiered { base, tiers } => {
                finite(*base)?;
                for tier in tiers {
                    if tier.start < 0.0 {
                        return Err(format!("{key} tier start must be non-negative"));
                    }
                    finite(tier.price)?;
                }
                Ok(())
            }
        }
    }
}

#[derive(Debug)]
pub(crate) struct ConditionalPrice {
    pub(crate) constraint: Option<Constraint>,
    pub(crate) prices: ModelPrice,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub(crate) enum Constraint {
    /// Active from midnight UTC of this date, as seconds since the Unix epoch.
    StartDate(i64),
    /// Active between two times of day, as seconds since midnight UTC. Wraps past midnight when
    /// `end < start`.
    TimeOfDay { start: f64, end: f64 },
}

impl Constraint {
    pub(crate) fn is_active(constraint: Option<&Self>, timestamp: Timestamp) -> bool {
        match constraint {
            None => true,
            Some(Self::StartDate(start)) => timestamp.seconds >= *start,
            Some(Self::TimeOfDay { start, end }) => {
                let seconds = timestamp.utc_seconds_of_day();
                if end < start { seconds >= *start || seconds < *end } else { seconds >= *start && seconds < *end }
            }
        }
    }
}

#[derive(Debug)]
pub(crate) struct PriceVariant {
    pub(crate) when: BTreeMap<String, String>,
    pub(crate) prices: ModelPrice,
    pub(crate) constraint: Option<Constraint>,
}

#[derive(Debug)]
pub(crate) struct UsageExtractor {
    pub(crate) api_flavor: String,
    pub(crate) root: ExtractPath,
    pub(crate) model_path: ExtractPath,
    pub(crate) mappings: Vec<UsageExtractorMapping>,
}

#[derive(Debug)]
pub(crate) struct UsageExtractorMapping {
    pub(crate) path: ExtractPath,
    pub(crate) dest: String,
    pub(crate) required: bool,
}

/// A non-empty path that ends with a key.
pub(crate) type ExtractPath = Vec<PathStep>;

#[derive(Debug)]
pub(crate) enum PathStep {
    Key(String),
    ArrayMatch {
        field: String,
        matcher: MatchLogic,
        /// The step as written in the provider data, for error messages.
        source: serde_json::Value,
    },
}

impl Model {
    /// The standard prices in effect at `timestamp`: the last conditional price whose constraint matches.
    pub(crate) fn active_price(&self, timestamp: Timestamp) -> &ModelPrice {
        match &self.prices {
            ModelPrices::Direct(prices) => prices,
            ModelPrices::Conditional(conditional) => conditional
                .iter()
                .rev()
                .find(|candidate| Constraint::is_active(candidate.constraint.as_ref(), timestamp))
                .map_or(&conditional[0].prices, |candidate| &candidate.prices),
        }
    }
}
