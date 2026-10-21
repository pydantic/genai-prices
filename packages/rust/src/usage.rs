use std::borrow::{Borrow, Cow};
use std::collections::BTreeMap;
use std::fmt;

/// Identifies a value reported by a provider, such as `input_tokens`.
///
/// Every registered unit has an associated constant, e.g. [`UsageKey::INPUT_TOKENS`]. Keys that are
/// not registered can still be built with [`From`]; they are reported in
/// [`PriceCalculation::warnings`](crate::PriceCalculation::warnings) instead of being priced.
#[derive(Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct UsageKey(Cow<'static, str>);

impl UsageKey {
    /// Creates a key from a static string without allocating.
    #[must_use]
    pub const fn from_static(key: &'static str) -> Self {
        Self(Cow::Borrowed(key))
    }

    /// Returns the key as a string slice.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Debug for UsageKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Debug::fmt(self.as_str(), f)
    }
}

impl fmt::Display for UsageKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl Borrow<str> for UsageKey {
    fn borrow(&self) -> &str {
        self.as_str()
    }
}

impl AsRef<str> for UsageKey {
    fn as_ref(&self) -> &str {
        self.as_str()
    }
}

impl From<&str> for UsageKey {
    fn from(key: &str) -> Self {
        Self(Cow::Owned(key.to_owned()))
    }
}

impl From<String> for UsageKey {
    fn from(key: String) -> Self {
        Self(Cow::Owned(key))
    }
}

impl serde::Serialize for UsageKey {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> serde::Deserialize<'de> for UsageKey {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        String::deserialize(deserializer).map(Self::from)
    }
}

/// The values reported for one API call, keyed by [`UsageKey`].
///
/// ```
/// use genai_prices::{Usage, UsageKey};
///
/// let usage = Usage::from([(UsageKey::INPUT_TOKENS, 1_000.0), (UsageKey::OUTPUT_TOKENS, 100.0)]);
/// assert_eq!(usage.get("input_tokens"), Some(&1_000.0));
/// ```
pub type Usage = BTreeMap<UsageKey, f64>;
