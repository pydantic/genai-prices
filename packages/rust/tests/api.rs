//! The public API against the bundled data. Mirrors the engine-level tests in `packages/go/api_test.go`.

// Exact float comparisons mirror the other engines' tests.
#![allow(clippy::float_cmp)]
#![cfg(feature = "bundled")]

mod common;

use common::{assert_close, calculator, date, error_kind, usage};
use genai_prices::{Calculator, ErrorKind, ExtractRequest, PriceRequest, Usage, UsageKey};

#[test]
fn calculate() {
    let usage = usage([(UsageKey::INPUT_TOKENS, 1_000.0), (UsageKey::OUTPUT_TOKENS, 100.0)]);
    let request = PriceRequest::new("gpt-5", &usage).with_provider_id("openai").with_timestamp(date(2026, 1, 1));
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
    let debug = format!("{:?}", Calculator::bundled());
    assert!(debug.starts_with("Calculator { providers: ") && debug.ends_with(", .. }") && debug.len() < 100, "{debug}");
}

#[test]
fn provider_selectors_follow_python() {
    let usage = usage([(UsageKey::INPUT_TOKENS, 1_000.0)]);
    let price = |request: PriceRequest<'_>| genai_prices::calculate(&request);
    // Whitespace around a provider ID is ignored, and the ID takes precedence over an API URL.
    let request = PriceRequest::new("gpt-5", &usage).with_provider_id(" OpenAI ").with_provider_api_url("https://x");
    assert_eq!(price(request).unwrap().provider_id, "openai");
    // A selector that is set but empty is looked up like any other, rather than treated as absent.
    for request in [
        PriceRequest::new("gpt-5", &usage).with_provider_id("  "),
        PriceRequest::new("gpt-5", &usage).with_provider_api_url(""),
    ] {
        assert_eq!(error_kind(&price(request)), Some(ErrorKind::ProviderNotFound));
    }
    // Model references are matched case-insensitively but not trimmed.
    assert_eq!(price(PriceRequest::new("GPT-5", &usage).with_provider_id("openai")).unwrap().model_id, "gpt-5");
    let padded = price(PriceRequest::new(" gpt-5 ", &usage).with_provider_id("openai"));
    assert_eq!(error_kind(&padded), Some(ErrorKind::ModelNotFound));
}

#[test]
fn reports_unsupported_usage() {
    let usage = Usage::from([("input_tokens", 1.0), ("unknown_tokens", 2.0)]);
    let calculation = genai_prices::calculate(&PriceRequest::new("gpt-5", &usage).with_provider_id("openai")).unwrap();
    assert_eq!(calculation.warnings, ["Unsupported usage key for standard pricing: unknown_tokens"]);
}

#[test]
fn calculate_errors() {
    let empty = Usage::new();
    let negative = usage([(UsageKey::INPUT_TOKENS, -1.0)]);
    let infinite = usage([(UsageKey::INPUT_TOKENS, f64::INFINITY)]);
    let cases = [
        ("missing model", PriceRequest::new("", &empty), ErrorKind::ProviderNotFound),
        (
            "missing model in a provider",
            PriceRequest::new("", &empty).with_provider_id("openai"),
            ErrorKind::ModelNotFound,
        ),
        (
            "unknown provider",
            PriceRequest::new("gpt-5", &empty).with_provider_id("missing"),
            ErrorKind::ProviderNotFound,
        ),
        ("unknown model", PriceRequest::new("missing", &empty).with_provider_id("openai"), ErrorKind::ModelNotFound),
        ("negative usage", PriceRequest::new("gpt-5", &negative).with_provider_id("openai"), ErrorKind::InvalidUsage),
        ("non-finite usage", PriceRequest::new("gpt-5", &infinite).with_provider_id("openai"), ErrorKind::InvalidUsage),
    ];
    for (name, request, kind) in cases {
        assert_eq!(error_kind(&genai_prices::calculate(&request)), Some(kind), "{name}");
    }
}

#[test]
fn rejects_price_overflow() {
    let calculator = calculator(
        r#"[{"id":"testing","name":"Testing","api_pattern":"testing",
            "models":[{"id":"model","match":{"equals":"model"},"prices":{"output_mtok":2}}]}]"#,
    );
    let usage = usage([(UsageKey::OUTPUT_TOKENS, f64::MAX)]);
    let request = PriceRequest::new("model", &usage).with_provider_id("testing");
    assert_eq!(error_kind(&calculator.calculate(&request)), Some(ErrorKind::InvalidUsage));
}

#[test]
fn duplicate_keys_use_the_last_value() {
    let calculator = calculator(
        r#"[{"id":"testing","name":"Testing","api_pattern":"testing",
            "models":[{"id":"model","match":{"equals":"model"},
                "prices":[{"prices":{"input_mtok":2}}],
                "prices":{"input_mtok":1}}]}]"#,
    );
    let usage = usage([(UsageKey::INPUT_TOKENS, 1_000_000.0)]);
    assert_eq!(
        calculator.calculate(&PriceRequest::new("model", &usage).with_provider_id("testing")).unwrap().total_price,
        1.0
    );
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
    let usage = usage([(UsageKey::INPUT_TOKENS, 1_000_000.0), (UsageKey::OUTPUT_TOKENS, 500_000.0)]);
    let calculation = calculator.calculate(&PriceRequest::new("test-model", &usage)).unwrap();
    assert_eq!((calculation.input_price, calculation.output_price, calculation.total_price), (2.0, 2.0, 4.0));
}

#[test]
fn from_json_rejects_invalid_data() {
    for data in ["{}", "null", "not JSON"] {
        assert_eq!(error_kind(&Calculator::from_json(data)), Some(ErrorKind::InvalidData), "{data}");
    }
    let error = Calculator::from_json("not JSON").unwrap_err();
    assert!(std::error::Error::source(&error).is_some(), "the serde_json error is kept as the source");
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
        ("gpt-6.1-terra", 1.0, 2.0),
    ] {
        for (tokens, rate) in [(272_000.0, base_rate), (272_001.0, long_rate)] {
            let usage = usage([(UsageKey::INPUT_TOKENS, tokens)]);
            let request =
                PriceRequest::new(model, &usage).with_provider_id("openai").with_timestamp(date(2026, 10, 27));
            let calculation = genai_prices::calculate(&request).unwrap();
            assert_close(calculation.input_price, tokens * rate / 1_000_000.0, 1e-12);
        }
    }
}

#[test]
fn databricks_provider_selection() {
    let model = "databricks-gpt-oss-120b";
    let one_million = usage([(UsageKey::INPUT_TOKENS, 1_000_000.0)]);
    for request in [
        PriceRequest::new(model, &one_million)
            .with_provider_api_url("https://my-workspace.cloud.databricks.com/serving-endpoints/chat/completions"),
        PriceRequest::new(model, &one_million).with_provider_api_url(
            "https://adb-1234567890123456.7.azuredatabricks.net/serving-endpoints/databricks-gpt-oss-120b/invocations",
        ),
        PriceRequest::new(model, &one_million).with_provider_api_url(
            "https://1234567890123456.7.gcp.databricks.com/ai-gateway/mlflow/v1/chat/completions",
        ),
        PriceRequest::new(model, &one_million),
        PriceRequest::new("system.ai.gpt-oss-120b", &one_million),
        PriceRequest::new("databricks/databricks-gpt-oss-120b", &one_million).with_provider_id("litellm"),
    ] {
        let calculation = genai_prices::calculate(&request).unwrap();
        assert_eq!(
            (calculation.provider_id.as_str(), calculation.model_id.as_str()),
            ("databricks", model),
            "{request:?}"
        );
        assert_close(calculation.total_price, 0.15, 1e-9);
    }

    let one = usage([(UsageKey::INPUT_TOKENS, 1.0)]);
    assert_eq!(genai_prices::calculate(&PriceRequest::new("kimi-k3", &one)).unwrap().provider_id, "moonshotai");

    for url in [
        "https://my-workspace.cloud.databricks.com.evil.test/serving-endpoints/chat/completions",
        "https://adb-1234567890123456.7.azuredatabricks.net.evil.test/serving-endpoints/databricks-gpt-oss-120b/invocations",
        "https://1234567890123456.7.gcp.databricks.com.evil.test/ai-gateway/mlflow/v1/chat/completions",
        "https://my-workspace.cloud.databricks.com/api/2.0/clusters/list",
    ] {
        let request = PriceRequest::new(model, &one).with_provider_api_url(url);
        assert_eq!(error_kind(&genai_prices::calculate(&request)), Some(ErrorKind::ProviderNotFound), "{url}");
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
        let extracted = genai_prices::extract_usage(&ExtractRequest::new(&body).with_provider_id("aws")).unwrap();
        // The raw reference is the response's; the matched ID is the price data's.
        let raw = genai_prices::extract_provider_usage(&ExtractRequest::new(&body).with_provider_id("aws")).unwrap();
        assert_eq!((raw.provider_id.as_str(), raw.model_ref.as_deref()), ("aws", Some(model)));
        assert_eq!(raw.usage, extracted.usage);
        assert!(extracted.model_id.as_deref().is_some_and(|id| id != model), "{:?}", extracted.model_id);
        assert_eq!(extracted.usage, want_usage);
        let request = extracted.price_request().unwrap().with_timestamp(date(2026, 10, 27));
        let price = genai_prices::calculate(&request).unwrap();
        assert_close(price.total_price, want_price, 1e-12);
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
        // The bytes and an already-parsed value must extract the same usage.
        let parsed: serde_json::Value = serde_json::from_str(body).unwrap();
        for request in [ExtractRequest::new(body), ExtractRequest::from_value(&parsed)] {
            let extracted =
                genai_prices::extract_usage(&request.with_provider_id("x-ai").with_api_flavor("responses")).unwrap();
            assert_eq!(extracted.model_id.as_deref(), Some("grok-4.20"));
            assert_eq!(extracted.usage, want_usage);
            let price = genai_prices::calculate(&extracted.price_request().unwrap()).unwrap();
            assert_eq!(price.model_id, "grok-4.20");
            assert_close(price.input_price, want_input, 1e-12);
            assert_close(price.output_price, 0.001_56, 1e-12);
            assert_close(price.total_price, want_total, 1e-12);
        }
    }
}

#[test]
fn results_serialize() {
    let usage = usage([(UsageKey::INPUT_TOKENS, 1_000_000.0)]);
    let calculator = calculator(
        r#"[{"id":"testing","name":"Testing","api_pattern":"testing",
            "extractors":[{"root":"usage","mappings":[{"path":"input","dest":"input_tokens","required":true}]}],
            "models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":2}}]}]"#,
    );
    let price = calculator.calculate(&PriceRequest::new("model", &usage).with_provider_id("testing")).unwrap();
    assert_eq!(
        serde_json::to_value(&price).unwrap(),
        serde_json::json!({"input_price": 2.0, "output_price": 0.0, "total_price": 2.0,
            "provider_id": "testing", "model_id": "model", "warnings": []}),
    );
    let extracted =
        calculator.extract_usage(&ExtractRequest::new(r#"{"usage":{"input":3}}"#).with_provider_id("testing")).unwrap();
    assert_eq!(extracted.price_request(), None);
    assert_eq!(
        serde_json::to_value(&extracted).unwrap(),
        serde_json::json!({"usage": {"input_tokens": 3.0}, "model_id": null, "provider_id": "testing", "warnings": []}),
    );
}

#[test]
fn usage_collection() {
    let mut usage: Usage = serde_json::from_str(r#"{"input_tokens": 1, "future_tokens": 2}"#).unwrap();
    assert_eq!(
        (usage.get("input_tokens"), usage.get("future_tokens"), usage.get("missing")),
        (Some(1.0), Some(2.0), None)
    );
    assert_eq!(serde_json::to_string(&usage).unwrap(), r#"{"future_tokens":2.0,"input_tokens":1.0}"#);
    assert_eq!(usage.insert(UsageKey::OUTPUT_TOKENS, 3.0), None);
    assert_eq!(usage.insert("output_tokens", 4.0), Some(3.0));
    assert!(usage.contains_key("output_tokens") && !usage.is_empty());
    assert_eq!(usage.remove("future_tokens"), Some(2.0));
    usage.extend([("cache_read_tokens", 0.5)]);
    let keys: Vec<&str> = usage.keys().map(UsageKey::as_str).collect();
    assert_eq!(keys, ["cache_read_tokens", "input_tokens", "output_tokens"]);
    let iter = usage.iter();
    assert_eq!(iter.len(), 3);
    assert_eq!(iter.map(|(_, value)| value).sum::<f64>(), 5.5);
    let collected: Usage = usage.clone().into_iter().collect();
    assert_eq!((collected.len(), collected), (3, usage));
    assert_eq!(Usage::new(), Usage::default());
}

#[test]
fn usage_keys() {
    assert_eq!(format!("{} {:?}", UsageKey::INPUT_TOKENS, UsageKey::INPUT_TOKENS), r#"input_tokens "input_tokens""#);
    assert_eq!(UsageKey::from(String::from("input_tokens")), UsageKey::INPUT_TOKENS);
    assert_eq!(UsageKey::from("future_tokens").as_str(), "future_tokens");
    assert_eq!(UsageKey::from(String::from("future_tokens")).as_str(), "future_tokens");
    assert_eq!(AsRef::<str>::as_ref(&UsageKey::INPUT_TOKENS), "input_tokens");
    assert_eq!(UsageKey::from_static("input_tokens"), UsageKey::INPUT_TOKENS);
}

#[test]
fn error_messages_name_the_failure() {
    let usage = Usage::new();
    let error = genai_prices::calculate(&PriceRequest::new("missing", &usage).with_provider_id("openai")).unwrap_err();
    assert_eq!(error.kind(), ErrorKind::ModelNotFound);
    assert_eq!(error.to_string(), r#"model not found: unable to find model with model_ref="missing" in openai"#);
}
