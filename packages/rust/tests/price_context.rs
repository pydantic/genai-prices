//! Request pricing context: the shared `tests/fixtures/price_context.json` contract plus the bundled
//! service-tier and batch rates. Mirrors `packages/go/price_context_test.go`.

// Exact float comparisons mirror the other engines' tests.
#![allow(clippy::float_cmp)]
#![cfg(feature = "bundled")]

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
        let mut request =
            PriceRequest::new("context-model", &fixture.usage).with_provider_id("testing").with_timestamp(timestamp);
        request.price_context = case.context.iter().map(|(key, value)| (key.as_str(), value.as_str())).collect();
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
        let usage = token_usage();
        let request = PriceRequest::new(model, &usage)
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
        let usage = token_usage();
        let request = PriceRequest::new(model, &usage)
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
        let request = PriceRequest::new(model, &usage)
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
            &PriceRequest::new("m", &Usage::new())
                .with_provider_id("testing")
                .with_price_context("service_tier", "flex"),
        )
        .unwrap_err();
    assert!(error.to_string().contains("missing ancestor"), "{error}");
}

#[test]
fn fallback_provider_does_not_inherit_tier_rates() {
    let usage = usage([(UsageKey::INPUT_TOKENS, 1_000_000.0), (UsageKey::OUTPUT_TOKENS, 1_000_000.0)]);
    for context in [vec![], vec![("service_tier", "priority")]] {
        let mut request =
            PriceRequest::new("gpt-5", &usage).with_provider_id("azure").with_timestamp(date(2026, 10, 12));
        request.price_context = context;
        let result = genai_prices::calculate(&request).unwrap();
        assert_eq!((result.provider_id.as_str(), result.total_price), ("azure", 11.25));
        assert!(result.warnings.is_empty(), "{:?}", result.warnings);
    }
}

#[test]
fn perplexity_responses_usage_and_search_type() {
    // Constructed from the Agent model/schema and Perplexity's synthetic usage test, not a recording:
    // https://docs.perplexity.ai/docs/agent-api/models
    // https://github.com/perplexityai/wandr/blob/9ea23c7f24d0aaabc2c87b26815a513001b2e7ce/agents/relay/tests/test_perplexity_usage.py
    // https://docs.perplexity.ai/docs/agent-api/tools/web-search
    let with_details = r#"{"model":"perplexity/sonar","object":"response","usage":{"input_tokens":1000,"input_tokens_details":{"cache_read_input_tokens":800,"cached_tokens":300},"output_tokens":100,"output_tokens_details":{"reasoning_tokens":50},"total_tokens":1100,"tool_calls_details":{"search_web":{"invocation":2}}}}"#;
    let without_details = r#"{"model":"perplexity/sonar","object":"response","usage":{"input_tokens":1000,"output_tokens":100,"total_tokens":1100}}"#;
    let cases = [
        (
            with_details,
            usage([
                (UsageKey::INPUT_TOKENS, 1_000.0),
                (UsageKey::CACHE_READ_TOKENS, 800.0),
                (UsageKey::OUTPUT_TOKENS, 100.0),
                (UsageKey::OUTPUT_REASONING_TOKENS, 50.0),
                (UsageKey::WEB_SEARCHES, 2.0),
            ]),
            0.0001,
            true,
        ),
        (
            without_details,
            usage([(UsageKey::INPUT_TOKENS, 1_000.0), (UsageKey::OUTPUT_TOKENS, 100.0)]),
            0.000_25,
            false,
        ),
    ];
    for (body, want_usage, want_input, with_tools) in cases {
        let request =
            genai_prices::ExtractRequest::new(body).with_provider_id("perplexity").with_api_flavor("responses");
        let extracted = genai_prices::extract_usage(&request).unwrap();
        assert_eq!(extracted.model.as_deref(), Some("perplexity/sonar"));
        assert_eq!(extracted.usage, want_usage);
        // The search type selects the rate independently of the request date.
        for (month, day, context, want_total) in [
            (10, 15, None, 0.005_35),
            (10, 15, Some("web"), 0.005_35),
            (9, 23, Some("fast"), 0.002_35),
            (9, 24, Some("fast"), 0.002_35),
            (10, 14, Some("fast"), 0.002_35),
            (10, 15, Some("fast"), 0.002_35),
        ] {
            let mut request = extracted.price_request().unwrap().with_timestamp(date(2026, month, day));
            if let Some(search_type) = context {
                request = request.with_price_context("search_type", search_type);
            }
            let price = genai_prices::calculate(&request).unwrap();
            let want_total = if with_tools { want_total } else { 0.0005 };
            assert_eq!(price.model_id, "perplexity/sonar");
            assert_close(price.input_price, want_input, 1e-12);
            assert_close(price.output_price, 0.000_25, 1e-12);
            assert_close(price.total_price, want_total, 1e-12);
        }
    }
}
