//! Behaviour that the shared parity suite does not pin down: malformed data shapes, floating-point
//! tolerance in usage decomposition, and error reporting.

// Exact float comparisons mirror the other engines' tests.
#![allow(clippy::float_cmp)]

mod common;

use common::{assert_close, calculator, usage};
use genai_prices::{Calculator, ErrorKind, ExtractRequest, PriceRequest, Usage, UsageKey};

fn provider(body: &str) -> String {
    format!(r#"[{{"id":"testing","name":"Testing","api_pattern":"testing",{body}}}]"#)
}

#[test]
fn rejects_malformed_shapes() {
    for data in [
        r#"[{"id":1,"name":"Testing","api_pattern":"testing"}]"#.to_owned(),
        r#"[{"id":"testing","name":"Testing","api_pattern":"testing","models":{}}]"#.to_owned(),
        r#"[{"id":"testing","name":"Testing","api_pattern":"testing","fallback_model_providers":[1]}]"#.to_owned(),
        "[1]".to_owned(),
        provider(
            r#""extractors":[{"root":"usage","mappings":[{"path":"input","dest":"input_tokens","required":"yes"}]}]"#,
        ),
        provider(
            r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1,"tiers":5}}}]"#,
        ),
        provider(
            r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":"1","tiers":[]}}}]"#,
        ),
        provider(
            r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1,"tiers":[{"start":1.5,"price":1}]}}}]"#,
        ),
        provider(
            r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1,"tiers":[{"start":1,"price":"1"}]}}}]"#,
        ),
        provider(
            r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1,"tiers":[1]}}}]"#,
        ),
        provider(
            r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{"prices":{}},{"constraint":null,"prices":{}}]}]"#,
        ),
        provider(
            r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{"prices":{}},{"constraint":5,"prices":{}}]}]"#,
        ),
        provider(
            r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{"prices":{}},{"constraint":{"type":null,"start_date":"2026-01-01"},"prices":{}}]}]"#,
        ),
        provider(
            r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{"prices":{}},{"constraint":{"type":"start_date","start_time":"01:00:00Z","end_time":"02:00:00Z"},"prices":{}}]}]"#,
        ),
        provider(
            r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{"prices":{}},{"constraint":{"start_date":1},"prices":{}}]}]"#,
        ),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"price_variants":[{"prices":{}}]}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"price_variants":[{"when":5,"prices":{}}]}]"#),
        provider(
            r#""models":[{"id":"model","match":{"equals":"model"},"price_variants":[{"when":{"a":"b"},"prices":5}]}]"#,
        ),
        provider(r#""models":[{"id":"model","match":{"and":"model"}}]"#),
        provider(r#""models":[{"id":"model","match":{"regex":1}}]"#),
        provider(r#""models":[{"id":"model","match":{"starts_with":["model"]}}]"#),
        provider(r#""models":[{"id":"model","match":5}]"#),
    ] {
        let result = Calculator::from_json(&data);
        assert_eq!(common::error_kind(&result), Some(ErrorKind::InvalidData), "accepted or misclassified {data}");
    }
}

#[test]
fn accepts_optional_fields_and_explicit_nulls() {
    let calculator = calculator(&provider(
        r#""model_match":null,"provider_match":null,"fallback_model_providers":null,
        "extractors":[{"api_flavor":"","root":"usage","mappings":[{"path":"input","dest":"input_tokens"},{"path":"note","dest":"output_tokens"}]}],
        "models":[
            {"id":"free","match":{"equals":"free"}},
            {"id":"timed","match":{"equals":"timed"},"prices":[{"prices":{"input_mtok":1}},
                {"constraint":{"type":"time_of_date","start_time":"00:00:00Z","end_time":"00:00:01Z"},"prices":{"input_mtok":2}}],
             "price_variants":[{"when":{"tier":"x"},"constraint":null,"prices":{"input_mtok":3,"output_mtok":null}}]}
        ]"#,
    ));
    let one = usage([(UsageKey::INPUT_TOKENS, 1.0)]);
    let free = calculator.calculate(&PriceRequest::new("free", &one).with_provider_id("testing"));
    assert_eq!(free.unwrap().total_price, 0.0);
    let million = usage([(UsageKey::INPUT_TOKENS, 1_000_000.0)]);
    let timed = PriceRequest::new("timed", &million)
        .with_provider_id("testing")
        .with_timestamp(common::utc(2026, 1, 1, 12, 0, 0));
    assert_eq!(calculator.calculate(&timed).unwrap().total_price, 1.0);
    let tiered = timed.clone().with_price_context("tier", "y").with_price_context("tier", "x");
    assert_eq!(calculator.calculate(&tiered).unwrap().total_price, 3.0, "the last duplicate context key wins");
    assert_eq!(calculator.calculate(&timed.with_price_context("tier", "y")).unwrap().total_price, 1.0);

    // Optional mappings skip values that are not numbers.
    let extracted = calculator
        .extract_usage(&ExtractRequest::new(r#"{"usage":{"input":5,"note":"n/a"}}"#).with_provider_id("testing"))
        .unwrap();
    assert_eq!(extracted.usage, usage([(UsageKey::INPUT_TOKENS, 5.0)]));
    assert_eq!(extracted.model, None);
}

#[test]
fn decomposition_tolerates_rounding_error() {
    let calculator = calculator(&provider(
        r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":1,"cache_read_mtok":1,"cache_write_mtok":1}}]"#,
    ));
    // 0.3 - (0.1 + 0.2) is about -5.6e-17, which is rounding error rather than inconsistent usage.
    let rounded =
        usage([(UsageKey::INPUT_TOKENS, 0.3), (UsageKey::CACHE_READ_TOKENS, 0.1), (UsageKey::CACHE_WRITE_TOKENS, 0.2)]);
    let calculation = calculator.calculate(&PriceRequest::new("model", &rounded).with_provider_id("testing")).unwrap();
    assert_close(calculation.input_price, 0.3 / 1e6, 1e-18);

    let overlapping =
        usage([(UsageKey::INPUT_TOKENS, 1.0), (UsageKey::CACHE_READ_TOKENS, 0.6), (UsageKey::CACHE_WRITE_TOKENS, 0.6)]);
    let error =
        calculator.calculate(&PriceRequest::new("model", &overlapping).with_provider_id("testing")).unwrap_err();
    assert_eq!(
        error.to_string(),
        "invalid usage: more-specific usage for cache_read_tokens, cache_write_tokens totals 1.2, \
         which exceeds input_tokens (1)",
    );

    let exceeding = usage([(UsageKey::INPUT_TOKENS, 1.0), (UsageKey::CACHE_READ_TOKENS, 2.0)]);
    let error = calculator.calculate(&PriceRequest::new("model", &exceeding).with_provider_id("testing")).unwrap_err();
    assert_eq!(error.to_string(), "invalid usage: cache_read_tokens (2) cannot exceed input_tokens (1)");
}

#[cfg(feature = "bundled")]
#[test]
fn unknown_model_without_a_provider() {
    let usage = Usage::new();
    let error = genai_prices::calculate(&PriceRequest::new("no-such-model", &usage)).unwrap_err();
    assert_eq!(error.kind(), ErrorKind::ProviderNotFound, "{error}");
}

#[test]
fn catastrophic_regex_fails_instead_of_hanging() {
    // A lookahead inside the repetition forces the backtracking engine, and two branches that match the same
    // text make it exponential. The backtrack limit plays the role of the Go engine's match timeout.
    let calculator = calculator(&provider(r#""models":[{"id":"model","match":{"regex":"^((?=a)a|a)+b"}}]"#));
    let (model, usage) = ("a".repeat(64), Usage::new());
    let error = calculator.calculate(&PriceRequest::new(&model, &usage).with_provider_id("testing")).unwrap_err();
    assert_eq!(error.kind(), ErrorKind::Match, "{error}");
}
