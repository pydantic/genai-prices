//! The public API against the bundled data. Mirrors the engine-level tests in `packages/go/api_test.go`.

// Exact float comparisons mirror the other engines' tests.
#![allow(clippy::float_cmp, clippy::type_complexity)]

mod common;

use common::{assert_close, calculator, date, usage};
use genai_prices::{Calculator, Error, ExtractRequest, PriceRequest, Usage, UsageKey};

#[test]
fn calculate() {
    let request =
        PriceRequest::new("gpt-5", usage([(UsageKey::INPUT_TOKENS, 1_000.0), (UsageKey::OUTPUT_TOKENS, 100.0)]))
            .with_provider_id("openai")
            .with_timestamp(date(2026, 1, 1));
    let calculation = genai_prices::calculate(&request).unwrap();
    assert_eq!((calculation.provider_id.as_str(), calculation.model_id.as_str()), ("openai", "gpt-5"));
    assert!(calculation.total_price > 0.0);
    assert!(calculation.warnings.is_empty());
}

#[test]
fn calculator_is_shareable_across_threads() {
    fn assert_send_sync<T: Send + Sync>() {}
    assert_send_sync::<Calculator>();
    assert!(std::ptr::eq(Calculator::bundled(), Calculator::bundled()));
}

#[test]
fn whitespace_provider_id_is_absent() {
    let mut request = PriceRequest::new("gpt-5", usage([(UsageKey::INPUT_TOKENS, 1_000.0)]))
        .with_provider_id("  ")
        .with_provider_api_url("https://api.openai.com");
    assert_eq!(genai_prices::calculate(&request).unwrap().provider_id, "openai");

    // An empty URL is absent too, so the provider is inferred from the model.
    request.provider_api_url = Some(String::new());
    assert_eq!(genai_prices::calculate(&request).unwrap().provider_id, "openai");
}

#[test]
fn reports_unsupported_usage() {
    let request = PriceRequest::new(
        "gpt-5",
        Usage::from([(UsageKey::INPUT_TOKENS, 1.0), (UsageKey::from("unknown_tokens"), 2.0)]),
    )
    .with_provider_id("openai");
    let calculation = genai_prices::calculate(&request).unwrap();
    assert_eq!(calculation.warnings, ["Unsupported usage key for standard pricing: unknown_tokens"]);
}

#[test]
fn calculate_errors() {
    let gpt5 = |usage: Usage| PriceRequest::new("gpt-5", usage).with_provider_id("openai");
    let cases: [(&str, PriceRequest, fn(&Error) -> bool); 6] = [
        ("missing model", PriceRequest::default(), |error| matches!(error, Error::ModelNotFound(_))),
        (
            "conflicting provider selectors",
            gpt5(Usage::new()).with_provider_api_url("https://api.openai.com"),
            |error| matches!(error, Error::InvalidUsage(_)),
        ),
        ("unknown provider", PriceRequest::new("gpt-5", Usage::new()).with_provider_id("missing"), |error| {
            matches!(error, Error::ProviderNotFound(_))
        }),
        ("unknown model", PriceRequest::new("missing", Usage::new()).with_provider_id("openai"), |error| {
            matches!(error, Error::ModelNotFound(_))
        }),
        ("negative usage", gpt5(usage([(UsageKey::INPUT_TOKENS, -1.0)])), |error| {
            matches!(error, Error::InvalidUsage(_))
        }),
        ("non-finite usage", gpt5(usage([(UsageKey::INPUT_TOKENS, f64::INFINITY)])), |error| {
            matches!(error, Error::InvalidUsage(_))
        }),
    ];
    for (name, request, expected) in cases {
        let error = genai_prices::calculate(&request).unwrap_err();
        assert!(expected(&error), "{name}: unexpected {error:?}");
    }
}

#[test]
fn rejects_price_overflow() {
    let calculator = calculator(
        r#"[{"id":"testing","name":"Testing","api_pattern":"testing",
            "models":[{"id":"model","match":{"equals":"model"},"prices":{"output_mtok":2}}]}]"#,
    );
    let request = PriceRequest::new("model", usage([(UsageKey::OUTPUT_TOKENS, f64::MAX)])).with_provider_id("testing");
    assert!(matches!(calculator.calculate(&request), Err(Error::InvalidUsage(_))));
}

#[test]
fn duplicate_keys_use_the_last_value() {
    let calculator = calculator(
        r#"[{"id":"testing","name":"Testing","api_pattern":"testing",
            "models":[{"id":"model","match":{"equals":"model"},
                "prices":[{"prices":{"input_mtok":2}}],
                "prices":{"input_mtok":1}}]}]"#,
    );
    let request =
        PriceRequest::new("model", usage([(UsageKey::INPUT_TOKENS, 1_000_000.0)])).with_provider_id("testing");
    assert_eq!(calculator.calculate(&request).unwrap().total_price, 1.0);
}

#[test]
fn from_json() {
    let calculator = calculator(
        r#"[{
            "id": "testing",
            "name": "Testing",
            "api_pattern": "https://testing\\.example",
            "model_match": {"starts_with": "test-"},
            "models": [{"id": "test-model", "match": {"equals": "test-model"}, "prices": {"input_mtok": 2, "output_mtok": 4}}]
        }]"#,
    );
    let request = PriceRequest::new(
        "test-model",
        usage([(UsageKey::INPUT_TOKENS, 1_000_000.0), (UsageKey::OUTPUT_TOKENS, 500_000.0)]),
    );
    let calculation = calculator.calculate(&request).unwrap();
    assert_eq!((calculation.input_price, calculation.output_price, calculation.total_price), (2.0, 2.0, 4.0));
}

#[test]
fn from_json_rejects_invalid_data() {
    for data in ["{}", "null", "not JSON"] {
        assert!(matches!(Calculator::from_json(data), Err(Error::InvalidData(_))), "{data}");
    }
}

#[test]
fn openai_long_context_boundary() {
    for (model, base_rate, long_rate) in [
        ("gpt-5.4", 2.5, 5.0),
        ("gpt-5.4-pro", 30.0, 60.0),
        ("gpt-5.5", 5.0, 10.0),
        ("gpt-5.5-pro", 30.0, 60.0),
        ("gpt-5.6-luna", 0.2, 0.4),
        ("gpt-5.6-sol", 4.0, 8.0),
        ("gpt-5.6-terra", 2.0, 4.0),
        ("gpt-6.1-sol", 2.0, 4.0),
    ] {
        for (tokens, rate) in [(272_000.0, base_rate), (272_001.0, long_rate)] {
            let request =
                PriceRequest::new(model, usage([(UsageKey::INPUT_TOKENS, tokens)])).with_provider_id("openai");
            let calculation = genai_prices::calculate(&request).unwrap();
            assert_close(calculation.input_price, tokens * rate / 1_000_000.0, 1e-12);
        }
    }
}

#[test]
fn databricks_provider_selection() {
    let model = "databricks-gpt-oss-120b";
    let one_million = || usage([(UsageKey::INPUT_TOKENS, 1_000_000.0)]);
    for request in [
        PriceRequest::new(model, one_million())
            .with_provider_api_url("https://my-workspace.cloud.databricks.com/serving-endpoints/chat/completions"),
        PriceRequest::new(model, one_million()).with_provider_api_url(
            "https://adb-1234567890123456.7.azuredatabricks.net/serving-endpoints/databricks-gpt-oss-120b/invocations",
        ),
        PriceRequest::new(model, one_million()).with_provider_api_url(
            "https://1234567890123456.7.gcp.databricks.com/ai-gateway/mlflow/v1/chat/completions",
        ),
        PriceRequest::new(model, one_million()),
        PriceRequest::new("system.ai.gpt-oss-120b", one_million()),
        PriceRequest::new("databricks/databricks-gpt-oss-120b", one_million()).with_provider_id("litellm"),
    ] {
        let calculation = genai_prices::calculate(&request).unwrap();
        assert_eq!(
            (calculation.provider_id.as_str(), calculation.model_id.as_str()),
            ("databricks", model),
            "{request:?}"
        );
        assert_close(calculation.total_price, 0.15, 1e-9);
    }

    let upstream =
        genai_prices::calculate(&PriceRequest::new("kimi-k3", usage([(UsageKey::INPUT_TOKENS, 1.0)]))).unwrap();
    assert_eq!(upstream.provider_id, "moonshotai");

    for url in [
        "https://my-workspace.cloud.databricks.com.evil.test/serving-endpoints/chat/completions",
        "https://adb-1234567890123456.7.azuredatabricks.net.evil.test/serving-endpoints/databricks-gpt-oss-120b/invocations",
        "https://1234567890123456.7.gcp.databricks.com.evil.test/ai-gateway/mlflow/v1/chat/completions",
        "https://my-workspace.cloud.databricks.com/api/2.0/clusters/list",
    ] {
        let request = PriceRequest::new(model, usage([(UsageKey::INPUT_TOKENS, 1.0)])).with_provider_api_url(url);
        assert!(matches!(genai_prices::calculate(&request), Err(Error::ProviderNotFound(_))), "{url}");
    }
}

#[test]
fn aws_converse_cache_write_ttl() {
    let want_usage = usage([
        (UsageKey::INPUT_TOKENS, 1_000_000.0),
        (UsageKey::CACHE_READ_TOKENS, 0.0),
        (UsageKey::CACHE_WRITE_TOKENS, 1_000_000.0),
        (UsageKey::CACHE_WRITE_5M_TOKENS, 750_000.0),
        (UsageKey::CACHE_WRITE_1H_TOKENS, 250_000.0),
        (UsageKey::OUTPUT_TOKENS, 0.0),
    ]);
    for (model, want_price) in
        [("global.anthropic.claude-sonnet-4-6", 4.3125), ("us.anthropic.claude-sonnet-4-6", 4.743_75)]
    {
        let body = format!(
            r#"{{"model":"{model}","usage":{{"inputTokens":0,"cacheReadInputTokens":0,"cacheWriteInputTokens":1000000,"cacheDetails":[{{"ttl":"1h","inputTokens":250000}},{{"ttl":"5m","inputTokens":750000}}],"outputTokens":0,"totalTokens":1000000}}}}"#
        );
        let extracted = genai_prices::extract_usage(&ExtractRequest::new(body).with_provider_id("aws")).unwrap();
        assert_eq!((extracted.provider_id.as_str(), extracted.model.as_deref()), ("aws", Some(model)));
        assert_eq!(extracted.usage, want_usage);
        let request = PriceRequest::new(model, extracted.usage).with_provider_id(extracted.provider_id);
        assert_close(genai_prices::calculate(&request).unwrap().total_price, want_price, 1e-12);
    }
}

#[test]
fn xai_responses_usage_and_price() {
    // Model and usage excerpt: https://docs.x.ai/developers/rest-api-reference/inference/responses
    // https://docs.x.ai/cookbook/examples/prompt-caching confirms reasoning is included in output_tokens.
    let with_details = r#"{"model":"grok-4.20-0309-reasoning","usage":{"input_tokens":131,"input_tokens_details":{"cached_tokens":128},"output_tokens":624,"output_tokens_details":{"reasoning_tokens":246},"total_tokens":755}}"#;
    let without_details =
        r#"{"model":"grok-4.20-0309-reasoning","usage":{"input_tokens":131,"output_tokens":624,"total_tokens":755}}"#;
    for (body, want_usage, want_input, want_total) in [
        (
            with_details,
            usage([
                (UsageKey::INPUT_TOKENS, 131.0),
                (UsageKey::CACHE_READ_TOKENS, 128.0),
                (UsageKey::OUTPUT_TOKENS, 624.0),
                (UsageKey::OUTPUT_REASONING_TOKENS, 246.0),
            ]),
            0.000_029_35,
            0.001_589_35,
        ),
        (
            without_details,
            usage([(UsageKey::INPUT_TOKENS, 131.0), (UsageKey::OUTPUT_TOKENS, 624.0)]),
            0.000_163_75,
            0.001_723_75,
        ),
    ] {
        let extracted = genai_prices::extract_usage(
            &ExtractRequest::new(body).with_provider_id("x-ai").with_api_flavor("responses"),
        )
        .unwrap();
        assert_eq!(extracted.model.as_deref(), Some("grok-4.20-0309-reasoning"));
        assert_eq!(extracted.usage, want_usage);
        let request =
            PriceRequest::new(extracted.model.unwrap(), extracted.usage).with_provider_id(extracted.provider_id);
        let price = genai_prices::calculate(&request).unwrap();
        assert_eq!(price.model_id, "grok-4.20");
        assert_close(price.input_price, want_input, 1e-12);
        assert_close(price.output_price, 0.001_56, 1e-12);
        assert_close(price.total_price, want_total, 1e-12);
    }
}

#[test]
fn usage_key_round_trips_through_serde() {
    let usage: Usage = serde_json::from_str(r#"{"input_tokens": 1, "future_tokens": 2}"#).unwrap();
    assert_eq!(usage[UsageKey::INPUT_TOKENS.as_str()], 1.0);
    assert_eq!(usage.get("future_tokens"), Some(&2.0));
    assert_eq!(serde_json::to_string(&usage).unwrap(), r#"{"future_tokens":2.0,"input_tokens":1.0}"#);
    assert_eq!(format!("{} {:?}", UsageKey::INPUT_TOKENS, UsageKey::INPUT_TOKENS), r#"input_tokens "input_tokens""#);
    assert_eq!(UsageKey::from(String::from("input_tokens")), UsageKey::INPUT_TOKENS);
    assert_eq!(AsRef::<str>::as_ref(&UsageKey::INPUT_TOKENS), "input_tokens");
}

#[test]
fn error_messages_name_the_failure() {
    let error =
        genai_prices::calculate(&PriceRequest::new("missing", Usage::new()).with_provider_id("openai")).unwrap_err();
    assert_eq!(error.to_string(), r#"model not found: "missing" in provider "openai""#);
}
