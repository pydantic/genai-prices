//! Matching, constraint resolution, tiered pricing, usage decomposition and extraction against synthetic
//! provider data. Mirrors `packages/go/parity_test.go` and the matching Python and JS tests: update them
//! together.

// Exact float comparisons mirror the other engines' tests.
#![allow(clippy::float_cmp, clippy::type_complexity)]

mod common;

use common::{assert_close, calculator, error_kind, usage, utc};
use genai_prices::{ErrorKind, ExtractRequest, PriceRequest, Usage, UsageKey};

#[test]
fn provider_and_model_matching() {
    let calculator = calculator(
        r#"[
        {
            "id":"source","name":"Source","api_pattern":"https://source\\.example",
            "provider_match":{"contains":"source-alias"},"model_match":{"starts_with":"source-"},
            "fallback_model_providers":["catalog"],
            "models":[
                {"id":"equals","match":{"equals":"source-equals"},"prices":{"input_mtok":1}},
                {"id":"contains","match":{"contains":"contains"},"prices":{"input_mtok":1}},
                {"id":"starts","match":{"starts_with":"source-start"},"prices":{"input_mtok":1}},
                {"id":"ends","match":{"ends_with":"-ends"},"prices":{"input_mtok":1}},
                {"id":"or","match":{"or":[{"equals":"source-or"},{"equals":"unused"}]},"prices":{"input_mtok":1}},
                {"id":"and","match":{"and":[{"starts_with":"source-"},{"ends_with":"-and"}]},"prices":{"input_mtok":1}},
                {"id":"regex","match":{"regex":"^(?!.*-tts$)source-regex"},"prices":{"input_mtok":1}}
            ]
        },
        {
            "id":"catalog","name":"Catalog","api_pattern":"https://catalog\\.example",
            "models":[{"id":"dated","match":{"equals":"model-2025-12-11"},"prices":{"input_mtok":2}}]
        },
        {
            "id":"fireworks","name":"Fireworks","api_pattern":"https://api\\.fireworks\\.ai",
            "provider_match":{"contains":"fireworks"},
            "model_match":{"starts_with":"accounts/fireworks/"},
            "models":[{"id":"deepseek-r1-0528","match":{"equals":"accounts/fireworks/models/deepseek-r1-0528"},"prices":{"input_mtok":1}}]
        }
    ]"#,
    );

    let cases: &[(&str, &str, Option<&str>, Option<&str>, &str)] = &[
        ("exact provider", "SOURCE-EQUALS", Some(" source "), None, "equals"),
        ("provider alias", "source-equals", Some("my-source-alias"), None, "equals"),
        ("provider URL", "source-contains-value", None, Some("https://source.example/v1"), "contains"),
        ("provider inference", "source-start-value", None, None, "starts"),
        ("ends", "source-value-ends", Some("source"), None, "ends"),
        ("or", "source-or", Some("source"), None, "or"),
        ("and", "source-value-and", Some("source"), None, "and"),
        ("regex", "source-regex-value", Some("source"), None, "regex"),
        ("fallback", "model-2025-12-11", Some("source"), None, "dated"),
        ("compact date", "model-20251211", Some("source"), None, "dated"),
        // Go also accepts " LiTeLLM "; Python, which Rust follows, does not trim the ID before this check.
        ("litellm", "source/source-equals", Some("LiTeLLM"), None, "equals"),
        (
            "litellm provider prefix",
            "fireworks_ai/accounts/fireworks/models/deepseek-r1-0528",
            Some("litellm"),
            None,
            "deepseek-r1-0528",
        ),
    ];
    let one = usage([(UsageKey::INPUT_TOKENS, 1.0)]);
    for &(name, model, provider_id, provider_api_url, want_model) in cases {
        let mut request = PriceRequest::new(model, &one);
        request.provider_id = provider_id;
        request.provider_api_url = provider_api_url;
        let calculation = calculator.calculate(&request).unwrap_or_else(|error| panic!("{name}: {error}"));
        assert_eq!(calculation.model_id, want_model, "{name}");
    }
    let empty = Usage::new();
    for model in ["source-regex-tts", "model-20250230"] {
        let error = calculator.calculate(&PriceRequest::new(model, &empty).with_provider_id("source"));
        assert_eq!(error_kind(&error), Some(ErrorKind::ModelNotFound), "{model}");
    }
}

#[test]
fn conditional_tiered_and_request_pricing() {
    let calculator = calculator(
        r#"[
        {
            "id":"testing","name":"Testing","api_pattern":"testing",
            "models":[
                {"id":"date","match":{"equals":"date"},"prices":[
                    {"prices":{"input_mtok":1}},
                    {"constraint":{"start_date":"2026-01-01"},"prices":{"input_mtok":2}}
                ]},
                {"id":"year-one","match":{"equals":"year-one"},"prices":[
                    {"prices":{"input_mtok":1}},
                    {"constraint":{"type":"start_date","start_date":"0001-01-01"},"prices":{"input_mtok":2}}
                ]},
                {"id":"day","match":{"equals":"day"},"prices":[
                    {"prices":{"input_mtok":1}},
                    {"constraint":{"start_time":"01:00:00Z","end_time":"02:00:00Z"},"prices":{"input_mtok":2}}
                ]},
                {"id":"wrap","match":{"equals":"wrap"},"prices":[
                    {"prices":{"input_mtok":1}},
                    {"constraint":{"start_time":"23:00:00+01:00","end_time":"01:00:00+01:00"},"prices":{"input_mtok":3}}
                ]},
                {"id":"tier","match":{"equals":"tier"},"prices":{"input_mtok":{"base":1,"tiers":[{"start":100,"price":2}]},"output_mtok":4}},
                {"id":"request","match":{"equals":"request"},"prices":{"requests_kcount":5}}
            ]
        }
    ]"#,
    );
    let million_input = || usage([(UsageKey::INPUT_TOKENS, 1_000_000.0)]);
    let cases = [
        ("date", Some(utc(2025, 12, 31, 23, 0, 0)), million_input(), 1.0),
        ("date", Some(utc(2026, 1, 1, 0, 0, 0)), million_input(), 2.0),
        ("year-one", Some(utc(2026, 1, 1, 0, 0, 0)), million_input(), 2.0),
        ("day", Some(utc(2026, 1, 1, 1, 30, 0)), million_input(), 2.0),
        ("day", Some(utc(2026, 1, 1, 2, 0, 0)), million_input(), 1.0),
        ("wrap", Some(utc(2026, 1, 1, 22, 30, 0)), million_input(), 3.0),
        ("wrap", Some(utc(2026, 1, 1, 0, 30, 0)), million_input(), 1.0),
        ("tier", None, usage([(UsageKey::INPUT_TOKENS, 100.0), (UsageKey::OUTPUT_TOKENS, 1_000_000.0)]), 4.0001),
        ("tier", None, usage([(UsageKey::INPUT_TOKENS, 101.0), (UsageKey::OUTPUT_TOKENS, 1_000_000.0)]), 4.000_202),
        ("request", None, Usage::new(), 0.005),
        ("date", Some(utc(2025, 1, 1, 0, 0, 0)), million_input(), 1.0),
    ];
    for (model, timestamp, usage, want) in &cases {
        let mut request = PriceRequest::new(model, usage).with_provider_id("testing");
        let timestamp = *timestamp;
        request.timestamp = timestamp;
        let calculation = calculator.calculate(&request).unwrap();
        assert_close(calculation.total_price, *want, 1e-12);
    }
}

#[test]
fn time_zone_normalization() {
    let calculator = calculator(
        r#"[
        {"id":"testing","name":"Testing","api_pattern":"testing","models":[
            {"id":"offset","match":{"equals":"offset"},"prices":[
                {"prices":{"input_mtok":1}},
                {"constraint":{"start_time":"00:30:00+01:00","end_time":"23:30:00-01:00"},"prices":{"input_mtok":2}}
            ]}
        ]}
    ]"#,
    );
    let usage = usage([(UsageKey::INPUT_TOKENS, 1_000_000.0)]);
    let request =
        PriceRequest::new("offset", &usage).with_provider_id("testing").with_timestamp(utc(2026, 1, 1, 12, 0, 0));
    assert_eq!(calculator.calculate(&request).unwrap().total_price, 1.0);
}

#[test]
fn tiered_pricing_requires_total_input_tokens() {
    let calculator = calculator(
        r#"[
        {"id":"testing","name":"Testing","api_pattern":"testing","models":[
            {"id":"model","match":{"equals":"model"},"prices":{"output_mtok":{"base":1,"tiers":[]}}}
        ]}
    ]"#,
    );
    let usage = usage([(UsageKey::INPUT_AUDIO_TOKENS, 1.0)]);
    let request = PriceRequest::new("model", &usage).with_provider_id("testing");
    assert_eq!(error_kind(&calculator.calculate(&request)), Some(ErrorKind::InvalidUsage));
}

#[test]
fn usage_decomposition_errors() {
    let calculator = calculator(
        r#"[
        {"id":"testing","name":"Testing","api_pattern":"testing","models":[
            {"id":"units","match":{"equals":"units"},"prices":{
                "input_mtok":1,"cache_read_mtok":2,"input_audio_mtok":3,"cache_audio_read_mtok":4
            }}
        ]}
    ]"#,
    );
    let valid = usage([
        (UsageKey::INPUT_TOKENS, 100.0),
        (UsageKey::CACHE_READ_TOKENS, 60.0),
        (UsageKey::INPUT_AUDIO_TOKENS, 40.0),
        (UsageKey::CACHE_AUDIO_READ_TOKENS, 10.0),
    ]);
    let calculation = calculator.calculate(&PriceRequest::new("units", &valid).with_provider_id("testing")).unwrap();
    assert_close(calculation.total_price, 0.000_24, 1e-15);

    let invalid = [
        usage([(UsageKey::INPUT_AUDIO_TOKENS, 1.0)]),
        usage([(UsageKey::CACHE_READ_TOKENS, 1.0), (UsageKey::INPUT_AUDIO_TOKENS, 1.0)]),
        usage([(UsageKey::INPUT_TOKENS, 1.0), (UsageKey::INPUT_AUDIO_TOKENS, 2.0)]),
        usage([(UsageKey::INPUT_TOKENS, 1.0), (UsageKey::CACHE_READ_TOKENS, 1.0), (UsageKey::INPUT_AUDIO_TOKENS, 1.0)]),
    ];
    for usage in invalid {
        let result = calculator.calculate(&PriceRequest::new("units", &usage).with_provider_id("testing"));
        assert_eq!(error_kind(&result), Some(ErrorKind::InvalidUsage), "usage {usage:?}");
    }
}

#[cfg(feature = "bundled")]
#[test]
fn groq_transcription_minimum() {
    let cases = [
        ("whisper-large-v3", Usage::new(), 0.0),
        ("whisper-large-v3", usage([(UsageKey::AUDIO_SECONDS, 1.0)]), 0.111 * 10.0 / 3600.0),
        (
            "whisper-large-v3",
            usage([(UsageKey::AUDIO_SECONDS, 0.0), (UsageKey::INPUT_AUDIO_SECONDS, 5.0)]),
            0.111 * 10.0 / 3600.0,
        ),
        ("whisper-large-v3-turbo", usage([(UsageKey::AUDIO_SECONDS, 11.0)]), 0.04 * 11.0 / 3600.0),
    ];
    for (model, usage, want) in cases {
        let calculation = genai_prices::calculate(&PriceRequest::new(model, &usage).with_provider_id("groq")).unwrap();
        assert_close(calculation.total_price, want, 1e-12);
    }
}

#[test]
fn extract_usage_paths_and_cloudflare_url() {
    let calculator = calculator(
        r#"[
        {
            "id":"testing","name":"Testing","api_pattern":"https://testing\\.example",
            "extractors":[{
                "api_flavor":"chat","root":"usage",
                "mappings":[
                    {"path":"input","dest":"input_tokens","required":true},
                    {"path":"input_2","dest":"input_tokens","required":false},
                    {"path":["details",{"type":"array-match","field":"kind","match":{"equals":"cached"}},"tokens"],"dest":"cache_read_tokens","required":false},
                    {"path":"ignored","dest":"future_tokens","required":false},
                    {"path":"also_ignored","dest":"future_tokens","required":false}
                ]
            }],
            "models":[{"id":"test-model","match":{"equals":"test-model"},"prices":{"input_mtok":1,"cache_read_mtok":0.5}}]
        },
        {
            "id":"cloudflare","name":"Cloudflare","api_pattern":"https://api\\.cloudflare\\.com",
            "extractors":[{"root":"usage","mappings":[{"path":"input","dest":"input_tokens","required":true}]}],
            "models":[{"id":"@cf/test/model","match":{"equals":"@cf/test/model"},"prices":{"input_mtok":1}}]
        }
    ]"#,
    );

    let extracted = calculator
        .extract_usage(
            &ExtractRequest::new(
                r#"{"model":"test-model","usage":{"input":10,"details":[null,{"kind":1,"tokens":50},{"kind":"cached","tokens":4}]}}"#,
            )
            .with_provider_id("testing")
            .with_api_flavor("chat"),
        )
        .unwrap();
    assert_eq!(extracted.model_id.as_deref(), Some("test-model"));
    assert_eq!(extracted.usage, usage([(UsageKey::INPUT_TOKENS, 10.0), (UsageKey::CACHE_READ_TOKENS, 4.0)]));
    assert_eq!(extracted.warnings.len(), 1);
    assert_eq!(extracted.warnings[0].matches("future_tokens").count(), 1);

    let overflow = calculator.extract_usage(
        &ExtractRequest::new(r#"{"usage":{"input":1e308,"input_2":1e308}}"#)
            .with_provider_id("testing")
            .with_api_flavor("chat"),
    );
    assert!(common::error_kind(&overflow) == Some(ErrorKind::InvalidUsage), "{overflow:?}");

    let cloudflare = calculator
        .extract_usage(
            // Go also passes a blank provider ID here and treats it as absent; Python looks it up and fails.
            &ExtractRequest::new(r#"{"usage":{"input":1}}"#)
                .with_provider_api_url("https://api.cloudflare.com/client/v4/accounts/a/ai/run/@cf/Test/Model"),
        )
        .unwrap();
    assert_eq!(cloudflare.model_id.as_deref(), Some("@cf/test/model"));
    let unknown = calculator
        .extract_usage(
            &ExtractRequest::new(r#"{"usage":{"input":1}}"#)
                .with_provider_api_url("https://api.cloudflare.com/client/v4/accounts/a/ai/run/@cf/unknown/model"),
        )
        .unwrap();
    assert_eq!(unknown.model_id, None);
}

#[test]
fn future_price_key_is_ignored() {
    let calculator = calculator(
        r#"[
        {"id":"testing","name":"Testing","api_pattern":"testing","models":[
            {"id":"model","match":{"equals":"model"},"prices":{"input_mtok":1,"future_mtok":99}}
        ]}
    ]"#,
    );
    let calculation = calculator
        .calculate(
            &PriceRequest::new("model", &usage([(UsageKey::INPUT_TOKENS, 1_000_000.0)])).with_provider_id("testing"),
        )
        .unwrap();
    assert_eq!(calculation.total_price, 1.0);
    assert_eq!(calculation.warnings, ["Unsupported price key for standard pricing: future_mtok"]);
}

#[test]
fn extract_usage_errors() {
    let calculator = calculator(
        r#"[
        {"id":"empty","name":"Empty","api_pattern":"empty","models":[]},
        {"id":"testing","name":"Testing","api_pattern":"testing","extractors":[
            {"api_flavor":"required","root":"usage","model_path":"model","mappings":[{"path":"input","dest":"input_tokens","required":true}]},
            {"api_flavor":"optional","root":"usage","model_path":"model","mappings":[{"path":["nested","input"],"dest":"input_tokens","required":false}]},
            {"api_flavor":"array","root":"usage","model_path":"model","mappings":[{"path":["items",{"type":"array-match","field":"kind","match":{"equals":"wanted"}},"value"],"dest":"input_tokens","required":true}]}
        ],"models":[]}
    ]"#,
    );
    let testing = |flavor: &'static str, body: &'static str| {
        ExtractRequest::new(body).with_provider_id("testing").with_api_flavor(flavor)
    };
    let empty = ExtractRequest::new("");
    let cases = [
        ("no selector", empty, ErrorKind::ProviderNotFound),
        // Go rejects both selectors; Python, which Rust follows, lets the provider ID win.
        ("both selectors", empty.with_provider_id("testing").with_provider_api_url("x"), ErrorKind::ExtractorNotFound),
        ("blank provider ID", empty.with_provider_id("  "), ErrorKind::ProviderNotFound),
        ("unknown provider", empty.with_provider_id("missing"), ErrorKind::ProviderNotFound),
        ("no extractors", empty.with_provider_id("empty"), ErrorKind::ExtractorNotFound),
        ("unknown flavor", empty.with_provider_id("testing"), ErrorKind::ExtractorNotFound),
        ("invalid JSON", testing("required", "x"), ErrorKind::InvalidResponse),
        ("non-mapping", testing("required", "[]"), ErrorKind::InvalidResponse),
        ("null response", testing("required", "null"), ErrorKind::InvalidResponse),
        ("boolean response", testing("required", "true"), ErrorKind::InvalidResponse),
        ("missing root", testing("required", "{}"), ErrorKind::InvalidResponse),
        ("wrong root", testing("required", r#"{"usage":1}"#), ErrorKind::InvalidResponse),
        ("missing required", testing("required", r#"{"usage":{}}"#), ErrorKind::InvalidResponse),
        ("wrong required type", testing("required", r#"{"usage":{"input":"1"}}"#), ErrorKind::InvalidResponse),
        ("wrong nested mapping", testing("optional", r#"{"usage":{"nested":true}}"#), ErrorKind::InvalidResponse),
        ("negative", testing("required", r#"{"usage":{"input":-1}}"#), ErrorKind::InvalidUsage),
        ("no optional usage", testing("optional", r#"{"usage":{"nested":1}}"#), ErrorKind::InvalidResponse),
        ("array expected", testing("array", r#"{"usage":{"items":{}}}"#), ErrorKind::InvalidResponse),
        (
            "array item missing",
            testing("array", r#"{"usage":{"items":[null,{"kind":1},{"kind":"other"}]}}"#),
            ErrorKind::InvalidResponse,
        ),
    ];
    for (name, request, kind) in cases {
        assert_eq!(error_kind(&calculator.extract_usage(&request)), Some(kind), "{name}");
    }
}

#[test]
fn invalid_provider_data() {
    let provider = |body: &str| format!(r#"[{{"id":"testing","name":"Testing","api_pattern":"testing",{body}}}]"#);
    let cases = [
        r#"[{"id":"","name":"Testing","api_pattern":"testing","models":[]}]"#.to_owned(),
        r#"[{"id":"Testing","name":"Testing","api_pattern":"testing","models":[]}]"#.to_owned(),
        r#"[{"id":"testing","name":"Testing","api_pattern":"testing","models":[]},{"id":"testing","name":"Other","api_pattern":"other","models":[]}]"#.to_owned(),
        r#"[{"id":"testing","name":"Testing","api_pattern":"[","models":[]}]"#.to_owned(),
        provider(r#""provider_match":{"equals":"a","contains":"b"},"models":[]"#),
        provider(r#""provider_match":{"regex":"["},"models":[]"#),
        provider(r#""provider_match":{"and":[{"regex":"["}]},"models":[]"#),
        provider(r#""provider_match":{"or":[{"regex":"["}]},"models":[]"#),
        provider(r#""extractors":[{"root":null,"mappings":[]}],"models":[]"#),
        provider(r#""extractors":[{"root":"usage","model_path":null,"mappings":[]}],"models":[]"#),
        provider(r#""extractors":[{"root":"usage","model_path":[],"mappings":[]}],"models":[]"#),
        provider(r#""extractors":[{"root":"usage","mappings":[{"path":null,"dest":"input_tokens","required":true}]}],"models":[]"#),
        provider(r#""extractors":[{"root":[{"type":"array-match","field":"kind","match":{"equals":"a"}}],"mappings":[]}],"models":[]"#),
        provider(r#""extractors":[{"root":[{"type":"wrong","field":"kind","match":{"equals":"a"}},"value"],"mappings":[]}],"models":[]"#),
        provider(r#""extractors":[{"root":[{"type":"array-match","field":"kind","match":{"regex":"["}},"value"],"mappings":[]}],"models":[]"#),
        provider(r#""extractors":[{"root":"usage","model_path":[{"type":"array-match","field":"kind","match":{"regex":"["}},"value"],"mappings":[]}],"models":[]"#),
        provider(r#""extractors":[{"root":"usage","mappings":[{"path":[{"type":"array-match","field":"kind","match":{"regex":"["}},"value"],"dest":"input_tokens"}]}],"models":[]"#),
        provider(r#""models":[{"id":"","match":{"equals":"model"},"prices":{}}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":{}},{"id":"model","match":{"equals":"other"},"prices":{}}]"#),
        provider(r#""models":[{"id":"model","match":{},"prices":{}}]"#),
        provider(r#""models":[{"id":"model","match":{"regex":"["},"prices":{}}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"cache_read_mtok":1}}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":1,"cache_read_mtok":1,"input_audio_mtok":1}}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":-1}}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1,"tiers":[{"start":-1,"price":2}]}}}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1,"tiers":[{"start":1,"price":-2}]}}}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":[]}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{"constraint":{"start_date":"2030-01-01"},"prices":{}}]}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{"prices":{}},{"prices":{}}]}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{}]}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{"constraint":{"start_date":"bad"},"prices":{}}]}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{"prices":{}},{"constraint":{"start_date":"0000-01-01"},"prices":{}}]}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{"prices":{}},{"constraint":{"start_date":"2026-01-01","tz":"UTC"},"prices":{}}]}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{"constraint":{"start_time":"bad","end_time":"01:00:00Z"},"prices":{}}]}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{"constraint":{"start_time":"00:00:00Z","end_time":"bad"},"prices":{}}]}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":[{"constraint":{},"prices":{}}]}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":"bad"}}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":null}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":1e10000}}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{}}}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1}}}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"tiers":[]}}}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1,"tiers":[{"price":2}]}}}]"#),
        provider(r#""models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1,"tiers":[{"start":1}]}}}]"#),
        provider(r#""extractors":[{"root":1,"mappings":[]}],"models":[]"#),
        provider(r#""extractors":[{"root":[1,"value"],"mappings":[]}],"models":[]"#),
        provider(r#""extractors":[{"root":[null,"value"],"mappings":[]}],"models":[]"#),
    ];
    for data in cases {
        let result = genai_prices::Calculator::from_json(&data);
        assert!(
            common::error_kind(&result) == Some(ErrorKind::InvalidData),
            "accepted or misclassified {data}: {result:?}"
        );
    }
}
