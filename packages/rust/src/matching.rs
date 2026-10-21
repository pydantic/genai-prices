//! Provider and model matching.

use std::borrow::Cow;
use std::sync::LazyLock;

use fancy_regex::{Captures, Regex};

use crate::error::{Error, ErrorKind, Result};
use crate::model::{Model, Provider};

/// A matching rule from the provider data. Every comparison is case-insensitive except `Regex`; literals are
/// stored lowercased so they are only folded once.
#[derive(Debug)]
pub(crate) enum MatchLogic {
    And(Vec<MatchLogic>),
    Or(Vec<MatchLogic>),
    Contains(String),
    EndsWith(String),
    Equals(String),
    Regex(Box<Regex>),
    StartsWith(String),
}

impl MatchLogic {
    pub(crate) fn matches(&self, subject: &Subject<'_>) -> Result<bool> {
        match self {
            Self::And(rules) => {
                for rule in rules {
                    if !rule.matches(subject)? {
                        return Ok(false);
                    }
                }
                Ok(true)
            }
            Self::Or(rules) => {
                for rule in rules {
                    if rule.matches(subject)? {
                        return Ok(true);
                    }
                }
                Ok(false)
            }
            Self::Contains(value) => Ok(subject.folded.contains(value.as_str())),
            Self::EndsWith(value) => Ok(subject.folded.ends_with(value.as_str())),
            Self::Equals(value) => Ok(*subject.folded == *value),
            Self::Regex(regex) => regex_matches(regex, subject.raw),
            Self::StartsWith(value) => Ok(subject.folded.starts_with(value.as_str())),
        }
    }
}

/// Text to match, lowercased once for every rule it is compared against.
pub(crate) struct Subject<'a> {
    raw: &'a str,
    folded: Cow<'a, str>,
}

impl<'a> Subject<'a> {
    pub(crate) fn new(raw: &'a str) -> Self {
        Self { raw, folded: fold_case(raw) }
    }
}

/// Lowercases `text`, borrowing it when it is already lowercase ASCII (the common case for model and provider IDs).
pub(crate) fn fold_case(text: &str) -> Cow<'_, str> {
    if text.bytes().any(|byte| !byte.is_ascii() || byte.is_ascii_uppercase()) {
        Cow::Owned(text.to_lowercase())
    } else {
        Cow::Borrowed(text)
    }
}

pub(crate) fn regex_matches(regex: &Regex, text: &str) -> Result<bool> {
    regex.is_match(text).map_err(|error| Error::new(ErrorKind::Match, format!("regex {:?}: {error}", regex.as_str())))
}

/// Finds a provider by exact ID, then by its `provider_match` alias rule.
pub(crate) fn find_provider_by_id(providers: &[Provider], provider_id: &str) -> Result<Option<usize>> {
    let normalized = fold_case(provider_id.trim());
    if let Some(index) = providers.iter().position(|provider| provider.id == normalized) {
        return Ok(Some(index));
    }
    let subject = Subject::new(&normalized);
    for (index, provider) in providers.iter().enumerate() {
        if let Some(rule) = &provider.provider_match {
            if rule.matches(&subject)? {
                return Ok(Some(index));
            }
        }
    }
    Ok(None)
}

/// Selects a provider by ID, then API URL, then by matching the model against each `model_match`.
pub(crate) fn find_provider(
    providers: &[Provider],
    model_id: &str,
    provider_id: Option<&str>,
    provider_api_url: Option<&str>,
) -> Result<Option<usize>> {
    if let Some(provider_id) = provider_id {
        let found = find_provider_by_id(providers, provider_id)?;
        // LiteLLM is a proxy rather than a provider, so fall through to the other selectors. As in Python, an ID with
        // surrounding whitespace is not LiteLLM here, although the lookup above ignores the whitespace.
        if found.is_some() || !provider_id.eq_ignore_ascii_case("litellm") {
            return Ok(found);
        }
    }
    if let Some(url) = provider_api_url {
        for (index, provider) in providers.iter().enumerate() {
            if regex_matches(&provider.api_regex, url)? {
                return Ok(Some(index));
            }
        }
        return Ok(None);
    }
    if !model_id.is_empty() {
        let subject = Subject::new(model_id);
        for (index, provider) in providers.iter().enumerate() {
            if let Some(rule) = &provider.model_match {
                if rule.matches(&subject)? {
                    return Ok(Some(index));
                }
            }
        }
    }
    Ok(None)
}

/// A model and the index of the provider that defines it, which differs from the selected provider
/// when the model came from one of its `fallback_model_providers`.
pub(crate) struct ModelMatch<'a> {
    pub(crate) provider: usize,
    pub(crate) model: &'a Model,
}

/// Finds a model in the selected provider or its fallbacks, retrying once with compact dates expanded.
pub(crate) fn find_model<'a>(
    providers: &'a [Provider],
    selected: usize,
    model_id: &str,
) -> Result<Option<ModelMatch<'a>>> {
    if let Some(found) = find_model_direct(providers, selected, model_id, true)? {
        return Ok(Some(found));
    }
    match normalize_compact_dated_ref(model_id) {
        Cow::Borrowed(_) => Ok(None),
        Cow::Owned(normalized) => find_model_direct(providers, selected, &normalized, true),
    }
}

fn find_model_direct<'a>(
    providers: &'a [Provider],
    selected: usize,
    model_id: &str,
    allow_fallback: bool,
) -> Result<Option<ModelMatch<'a>>> {
    let subject = Subject::new(model_id);
    for model in &providers[selected].models {
        if model.match_logic.matches(&subject)? {
            return Ok(Some(ModelMatch { provider: selected, model }));
        }
    }
    if allow_fallback {
        for fallback_id in &providers[selected].fallback_model_providers {
            for (index, fallback) in providers.iter().enumerate() {
                if fallback.id == *fallback_id {
                    if let Some(found) = find_model_direct(providers, index, model_id, false)? {
                        return Ok(Some(found));
                    }
                }
            }
        }
    }
    Ok(None)
}

static COMPACT_DATE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(-)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?=-|:|$)").expect("valid compact date pattern")
});

/// Rewrites compact date suffixes like `-20251211` to the canonical `-2025-12-11` form.
///
/// LiteLLM and OpenRouter emit compact dated model refs that don't match the dashed aliases used in the
/// price data. This is only a fallback for refs that don't otherwise match.
pub(crate) fn normalize_compact_dated_ref(model_id: &str) -> Cow<'_, str> {
    let normalized = COMPACT_DATE.replace_all(model_id, |captures: &Captures<'_, str>| {
        // `\d` matches any Unicode decimal digit, which Python's `int()` also accepts.
        let part = |index: usize| parse_decimal(&captures[index]);
        match (part(2), part(3), part(4)) {
            (Some(year), Some(month), Some(day)) if crate::time::is_valid_date(year, month, day) => {
                format!("-{year:04}-{month:02}-{day:02}")
            }
            _ => captures[0].to_owned(),
        }
    });
    // Matches that are not real dates are left as they were, which still produces an owned copy.
    match normalized {
        Cow::Owned(normalized) if normalized == model_id => Cow::Borrowed(model_id),
        normalized => normalized,
    }
}

/// The first code point of each run of ten Unicode decimal digits (general category `Nd`), as of Unicode 15.1.
/// Unicode guarantees that decimal digits come in such runs, so a digit's value is its offset from the run's start.
const DECIMAL_ZEROS: [u32; 68] = [
    0x0030, 0x0660, 0x06F0, 0x07C0, 0x0966, 0x09E6, 0x0A66, 0x0AE6, 0x0B66, 0x0BE6, 0x0C66, 0x0CE6, 0x0D66, 0x0DE6,
    0x0E50, 0x0ED0, 0x0F20, 0x1040, 0x1090, 0x17E0, 0x1810, 0x1946, 0x19D0, 0x1A80, 0x1A90, 0x1B50, 0x1BB0, 0x1C40,
    0x1C50, 0xA620, 0xA8D0, 0xA900, 0xA9D0, 0xA9F0, 0xAA50, 0xABF0, 0xFF10, 0x104A0, 0x10D30, 0x11066, 0x110F0,
    0x11136, 0x111D0, 0x112F0, 0x11450, 0x114D0, 0x11650, 0x116C0, 0x11730, 0x118E0, 0x11950, 0x11C50, 0x11D50,
    0x11DA0, 0x11F50, 0x16A60, 0x16AC0, 0x16B50, 0x1D7CE, 0x1D7D8, 0x1D7E2, 0x1D7EC, 0x1D7F6, 0x1E140, 0x1E2F0,
    0x1E4F0, 0x1E950, 0x1FBF0,
];

/// Parses a run of Unicode decimal digits, or returns `None` for anything else, including digits from a Unicode
/// version newer than [`DECIMAL_ZEROS`].
fn parse_decimal(text: &str) -> Option<i64> {
    text.chars().try_fold(0_i64, |total, digit| {
        let code = u32::from(digit);
        let zero = DECIMAL_ZEROS[DECIMAL_ZEROS.partition_point(|&zero| zero <= code).checked_sub(1)?];
        let value = code - zero;
        (value < 10).then(|| total * 10 + i64::from(value))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compact_dates() {
        assert_eq!(normalize_compact_dated_ref("gpt-5.2-20251211"), "gpt-5.2-2025-12-11");
        assert_eq!(normalize_compact_dated_ref("model-20251211:free"), "model-2025-12-11:free");
        assert_eq!(normalize_compact_dated_ref("a-20251211-20240229"), "a-2025-12-11-2024-02-29");
        assert_eq!(normalize_compact_dated_ref("model-20250230"), "model-20250230");
        assert_eq!(normalize_compact_dated_ref("model-202512110"), "model-202512110");
        assert_eq!(normalize_compact_dated_ref("model"), "model");
        // As in Python, any Unicode decimal digit matched by `\d` counts, but the literal month digits are ASCII.
        assert_eq!(normalize_compact_dated_ref("gpt-5-20\u{662}\u{665}1211"), "gpt-5-2025-12-11");
        assert_eq!(
            normalize_compact_dated_ref("gpt-5-2025\u{661}\u{662}\u{661}\u{661}"),
            "gpt-5-2025\u{661}\u{662}\u{661}\u{661}"
        );
    }

    #[test]
    fn decimal_digits() {
        assert_eq!(parse_decimal("2025"), Some(2025));
        assert_eq!(parse_decimal("\u{662}\u{665}"), Some(25));
        assert_eq!(parse_decimal("\u{1FBF9}"), Some(9));
        // Not digits: a letter, the code points either side of a run, and a superscript (category `No`).
        for invalid in ["x", "\u{2F}", "\u{3A}", "\u{1FBFA}", "\u{B2}"] {
            assert_eq!(parse_decimal(invalid), None, "{invalid:?}");
        }
    }
}
