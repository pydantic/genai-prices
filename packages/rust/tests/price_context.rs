//! Request pricing context: the shared `tests/fixtures/price_context.json` contract plus the bundled
//! service-tier and batch rates. Mirrors `packages/go/price_context_test.go`.

// Exact float comparisons mirror the other engines' tests.
#![allow(clippy::float_cmp, clippy::type_complexity)]

mod common;

use std::collections::BTreeMap;
use std::path::Path;

use common::{assert_close, calculator, date, usage};
use genai_prices::{Calculator, PriceRequest, Usage, UsageKey};
use serde::Deserialize;

#[derive(Deserialize)]
struct Fixture {
    providers: serde_json::Value,
    usage: Usage,
    cases: Vec<Case>,
}

#[derive(Deserialize)]
struct Case {
    name: String,
    timestamp: String,
    #[serde(default)]
    context: BTreeMap<String, String>,
    input: f64,
    output: f64,
    total: f64,
}

#[test]
fn price_context_contract() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/price_context.json");
    let fixture: Fixture = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    let calculator = Calculator::from_json(serde_json::to_vec(&fixture.providers).unwrap()).unwrap();
    for case in fixture.cases {
        let timestamp = chrono::DateTime::parse_from_rfc3339(&case.timestamp).unwrap();
        let mut request = PriceRequest::new("context-model", fixture.usage.clone())
            .with_provider_id("testing")
            .with_timestamp(timestamp);
        request.price_context = case.context;
        let result = calculator.calculate(&request).unwrap();
        assert_eq!(
            (result.input_price, result.output_price, result.total_price),
            (case.input, case.output, case.total),
            "{}",
            case.name,
        );
        assert!(result.warnings.is_empty(), "{}: {:?}", case.name, result.warnings);
    }
}

fn token_usage() -> Usage {
    usage([
        (UsageKey::INPUT_TOKENS, 1_000_000.0),
        (UsageKey::CACHE_READ_TOKENS, 250_000.0),
        (UsageKey::OUTPUT_TOKENS, 1_000_000.0),
    ])
}

#[test]
fn openai_service_tiers() {
    for (model, tier, total) in [
        ("o3", "flex", 4.8125),
        ("o3", "priority", 16.843_75),
        ("o4-mini", "flex", 2.647),
        ("o4-mini", "priority", 9.625),
        ("gpt-5-mini", "flex", 1.096_875),
        ("gpt-6.1-sol", "fast", 36.1),
        ("gpt-6.1-sol", "priority", 36.1),
    ] {
        let request = PriceRequest::new(model, token_usage())
            .with_provider_id("openai")
            .with_timestamp(date(2026, 10, 12))
            .with_price_context("service_tier", tier);
        let result = genai_prices::calculate(&request).unwrap();
        assert_close(result.total_price, total, 1e-12);
        assert!(result.warnings.is_empty(), "{model}/{tier}: {:?}", result.warnings);
    }
}

#[test]
fn batch_processing() {
    for (provider, model, timestamp, total) in [
        ("openai", "o3", date(2026, 10, 14), 4.875),
        ("anthropic", "claude-sonnet-5", date(2026, 10, 14), 5.775),
        ("google", "gemini-4-argon", date(2026, 10, 14), 5.7625),
        ("google", "gemini-4-argon", date(2026, 12, 1), 11.525),
        ("groq", "openai/gpt-oss-120b", date(2026, 10, 14), 0.375),
        ("mistral", "mistral-small-2603", date(2026, 10, 14), 0.358_125),
        ("x-ai", "grok-4.3", date(2026, 10, 14), 5.58),
    ] {
        let request = PriceRequest::new(model, token_usage())
            .with_provider_id(provider)
            .with_timestamp(timestamp)
            .with_price_context("processing", "batch");
        let result = genai_prices::calculate(&request).unwrap();
        assert_close(result.total_price, total, 1e-12);
        assert!(result.warnings.is_empty(), "{provider}/{model}: {:?}", result.warnings);
    }
}

#[test]
fn openai_published_flex_rates() {
    for (model, input_tokens, cache_read_tokens, input_price, output_price) in [
        ("o4-mini", 100_000.0, 100_000.0, 0.0138, 2.2),
        ("gpt-5.4", 272_000.0, 272_000.0, 0.035_36, 7.5),
        ("gpt-5.4", 272_001.0, 272_001.0, 0.068_000_25, 11.25),
        ("gpt-5.5-pro", 272_000.0, 0.0, 4.08, 90.0),
        ("gpt-5.5-pro", 272_001.0, 0.0, 4.080_015, 90.0),
    ] {
        let usage = usage([
            (UsageKey::INPUT_TOKENS, input_tokens),
            (UsageKey::CACHE_READ_TOKENS, cache_read_tokens),
            (UsageKey::OUTPUT_TOKENS, 1_000_000.0),
        ]);
        let request = PriceRequest::new(model, usage)
            .with_provider_id("openai")
            .with_timestamp(date(2026, 10, 12))
            .with_price_context("service_tier", "flex");
        let result = genai_prices::calculate(&request).unwrap();
        assert_close(result.input_price, input_price, 1e-12);
        assert_close(result.output_price, output_price, 1e-12);
        assert!(result.warnings.is_empty(), "{model}: {:?}", result.warnings);
    }
}

#[test]
fn invalid_price_variants() {
    for variant in [
        r#"{"when":{},"prices":{}}"#,
        r#"{"when":{"service_tier":null},"prices":{}}"#,
        r#"{"when":{"service_tier":true},"prices":{}}"#,
        r#"{"when":{"service_tier":"flex"}}"#,
        r#"{"when":{"service_tier":"flex"},"prices":{"input_mtok":-1}}"#,
        r#"{"when":{"service_tier":"flex"},"prices":{},"constraint":{"start_date":"bad"}}"#,
    ] {
        let data = format!(
            r#"[{{"id":"testing","name":"Testing","api_pattern":"testing","models":[{{"id":"m","match":{{"equals":"m"}},"prices":{{"input_mtok":1}},"price_variants":[{variant}]}}]}}]"#
        );
        assert!(Calculator::from_json(data).is_err(), "accepted invalid variant {variant}");
    }
    let calculator = calculator(
        r#"[{"id":"testing","name":"Testing","api_pattern":"testing","models":[{"id":"m","match":{"equals":"m"},"prices":{"input_mtok":1},"price_variants":[{"when":{"service_tier":"flex"},"prices":{"cache_image_read_mtok":1}}]}]}]"#,
    );
    let error = calculator
        .calculate(
            &PriceRequest::new("m", Usage::new())
                .with_provider_id("testing")
                .with_price_context("service_tier", "flex"),
        )
        .unwrap_err();
    assert!(error.to_string().contains("missing ancestor"), "{error}");
}

#[test]
fn fallback_provider_does_not_inherit_tier_rates() {
    let contexts = [BTreeMap::new(), BTreeMap::from([("service_tier".to_owned(), "priority".to_owned())])];
    for context in contexts {
        let mut request = PriceRequest::new(
            "gpt-5",
            usage([(UsageKey::INPUT_TOKENS, 1_000_000.0), (UsageKey::OUTPUT_TOKENS, 1_000_000.0)]),
        )
        .with_provider_id("azure")
        .with_timestamp(date(2026, 10, 12));
        request.price_context = context;
        let result = genai_prices::calculate(&request).unwrap();
        assert_eq!((result.provider_id.as_str(), result.total_price), ("azure", 11.25));
        assert!(result.warnings.is_empty(), "{:?}", result.warnings);
    }
}
