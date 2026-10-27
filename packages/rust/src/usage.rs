use std::borrow::{Borrow, Cow};
use std::collections::{BTreeMap, btree_map};
use std::fmt;

use crate::units::registered_usage_key;

/// Identifies a value reported by a provider, such as `input_tokens`.
///
/// Every registered unit has an associated constant, e.g. [`UsageKey::INPUT_TOKENS`]. Keys built with
/// [`From`] reuse the constant's static string when the key is registered, so they do not allocate. Keys
/// that are not registered are reported in [`PriceCalculation::warnings`](crate::PriceCalculation::warnings)
/// instead of being priced.
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
        registered_usage_key(key).map_or_else(|| Self(Cow::Owned(key.to_owned())), Self::from_static)
    }
}

impl From<String> for UsageKey {
    fn from(key: String) -> Self {
        registered_usage_key(&key).map_or_else(|| Self(Cow::Owned(key)), Self::from_static)
    }
}

impl serde::Serialize for UsageKey {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> serde::Deserialize<'de> for UsageKey {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        Cow::<'de, str>::deserialize(deserializer).map(|key| match key {
            Cow::Borrowed(key) => Self::from(key),
            Cow::Owned(key) => Self::from(key),
        })
    }
}

/// The values reported for one API call.
///
/// ```
/// use genai_prices::{Usage, UsageKey};
///
/// let mut usage = Usage::from([(UsageKey::INPUT_TOKENS, 1_000.0), (UsageKey::OUTPUT_TOKENS, 100.0)]);
/// usage.insert("cache_read_tokens", 200.0);
/// assert_eq!(usage.get("input_tokens"), Some(1_000.0));
/// assert_eq!(usage.len(), 3);
/// ```
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Usage(BTreeMap<UsageKey, f64>);

impl Usage {
    /// Creates empty usage.
    #[must_use]
    pub const fn new() -> Self {
        Self(BTreeMap::new())
    }

    /// The value reported for `key`, if any.
    #[must_use]
    pub fn get(&self, key: impl AsRef<str>) -> Option<f64> {
        self.0.get(key.as_ref()).copied()
    }

    /// Whether a value is reported for `key`.
    #[must_use]
    pub fn contains_key(&self, key: impl AsRef<str>) -> bool {
        self.0.contains_key(key.as_ref())
    }

    /// Sets the value for `key`, returning the previous value.
    pub fn insert(&mut self, key: impl Into<UsageKey>, value: f64) -> Option<f64> {
        self.0.insert(key.into(), value)
    }

    /// Removes the value for `key`, returning it.
    pub fn remove(&mut self, key: impl AsRef<str>) -> Option<f64> {
        self.0.remove(key.as_ref())
    }

    /// The number of reported values.
    #[must_use]
    pub fn len(&self) -> usize {
        self.0.len()
    }

    /// Whether no values are reported.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    /// Iterates over the reported values, ordered by key.
    #[must_use]
    pub fn iter(&self) -> Iter<'_> {
        Iter(self.0.iter())
    }

    /// Iterates over the reported keys, in order.
    pub fn keys(&self) -> impl Iterator<Item = &UsageKey> {
        self.0.keys()
    }

    pub(crate) fn add(&mut self, key: &str, value: f64) -> f64 {
        let total = self.0.entry(UsageKey::from(key)).or_insert(0.0);
        *total += value;
        *total
    }
}

impl<K: Into<UsageKey>, const N: usize> From<[(K, f64); N]> for Usage {
    fn from(values: [(K, f64); N]) -> Self {
        values.into_iter().collect()
    }
}

impl<K: Into<UsageKey>> FromIterator<(K, f64)> for Usage {
    fn from_iter<I: IntoIterator<Item = (K, f64)>>(values: I) -> Self {
        Self(values.into_iter().map(|(key, value)| (key.into(), value)).collect())
    }
}

impl<K: Into<UsageKey>> Extend<(K, f64)> for Usage {
    fn extend<I: IntoIterator<Item = (K, f64)>>(&mut self, values: I) {
        self.0.extend(values.into_iter().map(|(key, value)| (key.into(), value)));
    }
}

impl<'a> IntoIterator for &'a Usage {
    type Item = (&'a UsageKey, f64);
    type IntoIter = Iter<'a>;

    fn into_iter(self) -> Iter<'a> {
        self.iter()
    }
}

impl IntoIterator for Usage {
    type Item = (UsageKey, f64);
    type IntoIter = IntoIter;

    fn into_iter(self) -> IntoIter {
        IntoIter(self.0.into_iter())
    }
}

/// An iterator over the values in a [`Usage`], ordered by key.
#[derive(Debug, Clone)]
pub struct Iter<'a>(btree_map::Iter<'a, UsageKey, f64>);

impl<'a> Iterator for Iter<'a> {
    type Item = (&'a UsageKey, f64);

    fn next(&mut self) -> Option<Self::Item> {
        self.0.next().map(|(key, value)| (key, *value))
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        self.0.size_hint()
    }
}

impl ExactSizeIterator for Iter<'_> {}

/// An owning iterator over the values in a [`Usage`], ordered by key.
#[derive(Debug)]
pub struct IntoIter(btree_map::IntoIter<UsageKey, f64>);

impl Iterator for IntoIter {
    type Item = (UsageKey, f64);

    fn next(&mut self) -> Option<Self::Item> {
        self.0.next()
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        self.0.size_hint()
    }
}

impl ExactSizeIterator for IntoIter {}

impl serde::Serialize for Usage {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        self.0.serialize(serializer)
    }
}

impl<'de> serde::Deserialize<'de> for Usage {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        BTreeMap::deserialize(deserializer).map(Self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registered_keys_are_not_allocated() {
        assert!(matches!(UsageKey::from("input_tokens").0, Cow::Borrowed(_)));
        assert!(matches!(UsageKey::from(String::from("input_tokens")).0, Cow::Borrowed(_)));
        assert!(matches!(UsageKey::from("future_tokens").0, Cow::Owned(_)));
        let usage: Usage = serde_json::from_str(r#"{"input_tokens": 1}"#).unwrap();
        assert!(usage.keys().all(|key| matches!(key.0, Cow::Borrowed(_))));
    }
}
