package genai_prices_test

import (
	"errors"
	"math"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/pydantic/genai-prices/packages/go"
)

func TestProviderAndModelMatching(t *testing.T) {
	calculator := newTestCalculator(t, `[
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
		}
	]`)

	tests := []struct {
		name        string
		model       string
		providerID  string
		providerURL string
		wantModel   string
	}{
		{name: "exact provider", model: "SOURCE-EQUALS", providerID: " source ", wantModel: "equals"},
		{name: "provider alias", model: "source-equals", providerID: "my-source-alias", wantModel: "equals"},
		{name: "provider URL", model: "source-contains-value", providerURL: "https://source.example/v1", wantModel: "contains"},
		{name: "provider inference", model: "source-start-value", wantModel: "starts"},
		{name: "ends", model: "source-value-ends", providerID: "source", wantModel: "ends"},
		{name: "or", model: "source-or", providerID: "source", wantModel: "or"},
		{name: "and", model: "source-value-and", providerID: "source", wantModel: "and"},
		{name: "regex", model: "source-regex-value", providerID: "source", wantModel: "regex"},
		{name: "fallback", model: "model-2025-12-11", providerID: "source", wantModel: "dated"},
		{name: "compact date", model: "model-20251211", providerID: "source", wantModel: "dated"},
		{name: "litellm", model: "source/source-equals", providerID: " LiTeLLM ", wantModel: "equals"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			calculation, err := calculator.Calculate(genai_prices.PriceRequest{
				Usage:          genai_prices.Usage{genai_prices.UsageInputTokens: 1},
				Model:          test.model,
				ProviderID:     test.providerID,
				ProviderAPIURL: test.providerURL,
			})
			if err != nil {
				t.Fatal(err)
			}
			if calculation.ModelID != test.wantModel {
				t.Fatalf("got model %q, want %q", calculation.ModelID, test.wantModel)
			}
		})
	}
	for _, model := range []string{"source-regex-tts", "model-20250230"} {
		_, err := calculator.Calculate(genai_prices.PriceRequest{Model: model, ProviderID: "source"})
		if !errors.Is(err, genai_prices.ErrModelNotFound) {
			t.Fatalf("got %v", err)
		}
	}
}

func TestConditionalTieredAndRequestPricing(t *testing.T) {
	calculator := newTestCalculator(t, `[
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
	]`)

	tests := []struct {
		model     string
		timestamp time.Time
		usage     genai_prices.Usage
		want      float64
	}{
		{model: "date", timestamp: time.Date(2025, 12, 31, 23, 0, 0, 0, time.UTC), usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000}, want: 1},
		{model: "date", timestamp: time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC), usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000}, want: 2},
		{model: "year-one", timestamp: time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC), usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000}, want: 2},
		{model: "day", timestamp: time.Date(2026, 1, 1, 1, 30, 0, 0, time.UTC), usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000}, want: 2},
		{model: "day", timestamp: time.Date(2026, 1, 1, 2, 0, 0, 0, time.UTC), usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000}, want: 1},
		{model: "wrap", timestamp: time.Date(2026, 1, 1, 22, 30, 0, 0, time.UTC), usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000}, want: 3},
		{model: "wrap", timestamp: time.Date(2026, 1, 1, 0, 30, 0, 0, time.UTC), usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000}, want: 1},
		{model: "tier", usage: genai_prices.Usage{genai_prices.UsageInputTokens: 100, genai_prices.UsageOutputTokens: 1_000_000}, want: 4.0001},
		{model: "tier", usage: genai_prices.Usage{genai_prices.UsageInputTokens: 101, genai_prices.UsageOutputTokens: 1_000_000}, want: 4.000202},
		{model: "request", want: 0.005},
		{model: "date", timestamp: time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC), usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000}, want: 1},
	}
	for _, test := range tests {
		calculation, err := calculator.Calculate(genai_prices.PriceRequest{
			Usage: test.usage, Model: test.model, ProviderID: "testing", Timestamp: test.timestamp,
		})
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(calculation.TotalPrice-test.want) > 1e-12 {
			t.Errorf("%s: got %g, want %g", test.model, calculation.TotalPrice, test.want)
		}
	}
}

func TestTimeZoneNormalization(t *testing.T) {
	calculator := newTestCalculator(t, `[
		{"id":"testing","name":"Testing","api_pattern":"testing","models":[
			{"id":"offset","match":{"equals":"offset"},"prices":[
				{"prices":{"input_mtok":1}},
				{"constraint":{"start_time":"00:30:00+01:00","end_time":"23:30:00-01:00"},"prices":{"input_mtok":2}}
			]}
		]}
	]`)
	calculation, err := calculator.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000},
		Model: "offset", ProviderID: "testing", Timestamp: time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatal(err)
	}
	if calculation.TotalPrice != 1 {
		t.Fatalf("got %g", calculation.TotalPrice)
	}
}

func TestTieredPricingRequiresTotalInputTokens(t *testing.T) {
	calculator := newTestCalculator(t, `[
		{"id":"testing","name":"Testing","api_pattern":"testing","models":[
			{"id":"model","match":{"equals":"model"},"prices":{"output_mtok":{"base":1,"tiers":[]}}}
		]}
	]`)
	_, err := calculator.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{genai_prices.UsageInputAudioTokens: 1}, Model: "model", ProviderID: "testing",
	})
	if !errors.Is(err, genai_prices.ErrInvalidUsage) {
		t.Fatal(err)
	}
}

func TestUsageDecompositionErrors(t *testing.T) {
	calculator := newTestCalculator(t, `[
		{"id":"testing","name":"Testing","api_pattern":"testing","models":[
			{"id":"units","match":{"equals":"units"},"prices":{
				"input_mtok":1,"cache_read_mtok":2,"input_audio_mtok":3,"cache_audio_read_mtok":4
			}}
		]}
	]`)
	calculation, err := calculator.Calculate(genai_prices.PriceRequest{
		Model: "units", ProviderID: "testing",
		Usage: genai_prices.Usage{
			genai_prices.UsageInputTokens:          100,
			genai_prices.UsageCacheReadTokens:      60,
			genai_prices.UsageInputAudioTokens:     40,
			genai_prices.UsageCacheAudioReadTokens: 10,
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if math.Abs(calculation.TotalPrice-0.00024) > 1e-15 {
		t.Fatalf("got %g", calculation.TotalPrice)
	}

	invalid := []genai_prices.Usage{
		{genai_prices.UsageInputAudioTokens: 1},
		{genai_prices.UsageCacheReadTokens: 1, genai_prices.UsageInputAudioTokens: 1},
		{genai_prices.UsageInputTokens: 1, genai_prices.UsageInputAudioTokens: 2},
		{genai_prices.UsageInputTokens: 1, genai_prices.UsageCacheReadTokens: 1, genai_prices.UsageInputAudioTokens: 1},
	}
	for _, usage := range invalid {
		_, err := calculator.Calculate(genai_prices.PriceRequest{Usage: usage, Model: "units", ProviderID: "testing"})
		if !errors.Is(err, genai_prices.ErrInvalidUsage) {
			t.Fatalf("usage %v: got %v", usage, err)
		}
	}
}

func TestGroqTranscriptionMinimum(t *testing.T) {
	tests := []struct {
		model string
		usage genai_prices.Usage
		want  float64
	}{
		{model: "whisper-large-v3", usage: genai_prices.Usage{}, want: 0},
		{model: "whisper-large-v3", usage: genai_prices.Usage{genai_prices.UsageAudioSeconds: 1}, want: 0.111 * 10 / 3600},
		{model: "whisper-large-v3", usage: genai_prices.Usage{genai_prices.UsageAudioSeconds: 0, genai_prices.UsageInputAudioSeconds: 5}, want: 0.111 * 10 / 3600},
		{model: "whisper-large-v3-turbo", usage: genai_prices.Usage{genai_prices.UsageAudioSeconds: 11}, want: 0.04 * 11 / 3600},
	}
	for _, test := range tests {
		calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{Usage: test.usage, Model: test.model, ProviderID: "groq"})
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(calculation.TotalPrice-test.want) > 1e-12 {
			t.Errorf("got %g, want %g", calculation.TotalPrice, test.want)
		}
	}
}

func TestExtractUsagePathsAndCloudflareURL(t *testing.T) {
	calculator := newTestCalculator(t, `[
		{
			"id":"testing","name":"Testing","api_pattern":"https://testing\\.example",
			"extractors":[{
				"api_flavor":"chat","root":"usage",
				"mappings":[
					{"path":"input","dest":"input_tokens","required":true},
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
	]`)

	extracted, err := calculator.ExtractUsage(genai_prices.ExtractRequest{
		ResponseJSON: []byte(`{"model":"test-model","usage":{"input":10,"details":[null,{"kind":1,"tokens":50},{"kind":"cached","tokens":4}]}}`),
		ProviderID:   "testing",
		APIFlavor:    "chat",
	})
	if err != nil {
		t.Fatal(err)
	}
	if extracted.Model != "test-model" || extracted.Usage[genai_prices.UsageInputTokens] != 10 || extracted.Usage[genai_prices.UsageCacheReadTokens] != 4 {
		t.Fatalf("unexpected extraction: %#v", extracted)
	}
	if len(extracted.Warnings) != 1 || strings.Count(extracted.Warnings[0], "future_tokens") != 1 {
		t.Fatalf("unexpected warnings: %v", extracted.Warnings)
	}

	cloudflare, err := calculator.ExtractUsage(genai_prices.ExtractRequest{
		ResponseJSON:   []byte(`{"usage":{"input":1}}`),
		ProviderAPIURL: "https://api.cloudflare.com/client/v4/accounts/a/ai/run/@cf/test/model",
	})
	if err != nil {
		t.Fatal(err)
	}
	if cloudflare.Model != "@cf/test/model" {
		t.Fatalf("got %q", cloudflare.Model)
	}
	unknownCloudflare, err := calculator.ExtractUsage(genai_prices.ExtractRequest{
		ResponseJSON:   []byte(`{"usage":{"input":1}}`),
		ProviderAPIURL: "https://api.cloudflare.com/client/v4/accounts/a/ai/run/@cf/unknown/model",
	})
	if err != nil {
		t.Fatal(err)
	}
	if unknownCloudflare.Model != "" {
		t.Fatalf("got %q", unknownCloudflare.Model)
	}
}

func TestFuturePriceKeyIsIgnored(t *testing.T) {
	calculator := newTestCalculator(t, `[
		{"id":"testing","name":"Testing","api_pattern":"testing","models":[
			{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":1,"future_mtok":99}}
		]}
	]`)
	calculation, err := calculator.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000}, Model: "model", ProviderID: "testing",
	})
	if err != nil {
		t.Fatal(err)
	}
	if calculation.TotalPrice != 1 {
		t.Fatalf("got %g", calculation.TotalPrice)
	}
	if len(calculation.Warnings) != 1 || !strings.Contains(calculation.Warnings[0], "future_mtok") {
		t.Fatalf("unexpected warnings: %v", calculation.Warnings)
	}
}

func TestExtractUsageErrors(t *testing.T) {
	calculator := newTestCalculator(t, `[
		{"id":"empty","name":"Empty","api_pattern":"empty","models":[]},
		{"id":"testing","name":"Testing","api_pattern":"testing","extractors":[
			{"api_flavor":"required","root":"usage","model_path":"model","mappings":[{"path":"input","dest":"input_tokens","required":true}]},
			{"api_flavor":"optional","root":"usage","model_path":"model","mappings":[{"path":["nested","input"],"dest":"input_tokens","required":false}]},
			{"api_flavor":"array","root":"usage","model_path":"model","mappings":[{"path":["items",{"type":"array-match","field":"kind","match":{"equals":"wanted"}},"value"],"dest":"input_tokens","required":true}]}
		],"models":[]}
	]`)
	tests := []struct {
		name    string
		request genai_prices.ExtractRequest
		target  error
	}{
		{name: "no selector", request: genai_prices.ExtractRequest{}, target: genai_prices.ErrProviderNotFound},
		{name: "both selectors", request: genai_prices.ExtractRequest{ProviderID: "testing", ProviderAPIURL: "testing"}, target: genai_prices.ErrInvalidUsage},
		{name: "unknown provider", request: genai_prices.ExtractRequest{ProviderID: "missing"}, target: genai_prices.ErrProviderNotFound},
		{name: "no extractors", request: genai_prices.ExtractRequest{ProviderID: "empty"}, target: genai_prices.ErrExtractorNotFound},
		{name: "unknown flavor", request: genai_prices.ExtractRequest{ProviderID: "testing"}, target: genai_prices.ErrExtractorNotFound},
		{name: "invalid JSON", request: genai_prices.ExtractRequest{ProviderID: "testing", APIFlavor: "required", ResponseJSON: []byte(`x`)}, target: nil},
		{name: "non-mapping", request: genai_prices.ExtractRequest{ProviderID: "testing", APIFlavor: "required", ResponseJSON: []byte(`[]`)}, target: nil},
		{name: "null response", request: genai_prices.ExtractRequest{ProviderID: "testing", APIFlavor: "required", ResponseJSON: []byte(`null`)}, target: nil},
		{name: "boolean response", request: genai_prices.ExtractRequest{ProviderID: "testing", APIFlavor: "required", ResponseJSON: []byte(`true`)}, target: nil},
		{name: "missing root", request: genai_prices.ExtractRequest{ProviderID: "testing", APIFlavor: "required", ResponseJSON: []byte(`{}`)}, target: nil},
		{name: "wrong root", request: genai_prices.ExtractRequest{ProviderID: "testing", APIFlavor: "required", ResponseJSON: []byte(`{"usage":1}`)}, target: nil},
		{name: "missing required", request: genai_prices.ExtractRequest{ProviderID: "testing", APIFlavor: "required", ResponseJSON: []byte(`{"usage":{}}`)}, target: nil},
		{name: "wrong required type", request: genai_prices.ExtractRequest{ProviderID: "testing", APIFlavor: "required", ResponseJSON: []byte(`{"usage":{"input":"1"}}`)}, target: nil},
		{name: "wrong nested mapping", request: genai_prices.ExtractRequest{ProviderID: "testing", APIFlavor: "optional", ResponseJSON: []byte(`{"usage":{"nested":true}}`)}, target: nil},
		{name: "negative", request: genai_prices.ExtractRequest{ProviderID: "testing", APIFlavor: "required", ResponseJSON: []byte(`{"usage":{"input":-1}}`)}, target: genai_prices.ErrInvalidUsage},
		{name: "no optional usage", request: genai_prices.ExtractRequest{ProviderID: "testing", APIFlavor: "optional", ResponseJSON: []byte(`{"usage":{"nested":1}}`)}, target: nil},
		{name: "array expected", request: genai_prices.ExtractRequest{ProviderID: "testing", APIFlavor: "array", ResponseJSON: []byte(`{"usage":{"items":{}}}`)}, target: nil},
		{name: "array item missing", request: genai_prices.ExtractRequest{ProviderID: "testing", APIFlavor: "array", ResponseJSON: []byte(`{"usage":{"items":[null,{"kind":1},{"kind":"other"}]}}`)}, target: nil},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := calculator.ExtractUsage(test.request)
			if err == nil {
				t.Fatal("expected an error")
			}
			if test.target != nil && !errors.Is(err, test.target) {
				t.Fatalf("got %v, want %v", err, test.target)
			}
		})
	}
}

func TestNilCalculator(t *testing.T) {
	var calculator *genai_prices.Calculator
	if _, err := calculator.Calculate(genai_prices.PriceRequest{}); !errors.Is(err, genai_prices.ErrInvalidData) {
		t.Fatal(err)
	}
	if _, err := calculator.ExtractUsage(genai_prices.ExtractRequest{}); !errors.Is(err, genai_prices.ErrInvalidData) {
		t.Fatal(err)
	}
}

func TestInvalidProviderData(t *testing.T) {
	provider := func(body string) string {
		return `[{"id":"testing","name":"Testing","api_pattern":"testing",` + body + `}]`
	}
	tests := []string{
		`[{"id":"","name":"Testing","api_pattern":"testing","models":[]}]`,
		`[{"id":"testing","name":"Testing","api_pattern":"testing","models":[]},{"id":"testing","name":"Other","api_pattern":"other","models":[]}]`,
		`[{"id":"testing","name":"Testing","api_pattern":"[","models":[]}]`,
		provider(`"provider_match":{"equals":"a","contains":"b"},"models":[]`),
		provider(`"provider_match":{"regex":"["},"models":[]`),
		provider(`"provider_match":{"and":[{"regex":"["}]},"models":[]`),
		provider(`"provider_match":{"or":[{"regex":"["}]},"models":[]`),
		provider(`"extractors":[{"root":null,"mappings":[]}],"models":[]`),
		provider(`"extractors":[{"root":"usage","model_path":null,"mappings":[]}],"models":[]`),
		provider(`"extractors":[{"root":"usage","model_path":[],"mappings":[]}],"models":[]`),
		provider(`"extractors":[{"root":"usage","mappings":[{"path":null,"dest":"input_tokens","required":true}]}],"models":[]`),
		provider(`"extractors":[{"root":[{"type":"array-match","field":"kind","match":{"equals":"a"}}],"mappings":[]}],"models":[]`),
		provider(`"extractors":[{"root":[{"type":"wrong","field":"kind","match":{"equals":"a"}},"value"],"mappings":[]}],"models":[]`),
		provider(`"extractors":[{"root":[{"type":"array-match","field":"kind","match":{"regex":"["}},"value"],"mappings":[]}],"models":[]`),
		provider(`"extractors":[{"root":"usage","model_path":[{"type":"array-match","field":"kind","match":{"regex":"["}},"value"],"mappings":[]}],"models":[]`),
		provider(`"extractors":[{"root":"usage","mappings":[{"path":[{"type":"array-match","field":"kind","match":{"regex":"["}},"value"],"dest":"input_tokens"}]}],"models":[]`),
		provider(`"models":[{"id":"","match":{"equals":"model"},"prices":{}}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":{}},{"id":"model","match":{"equals":"other"},"prices":{}}]`),
		provider(`"models":[{"id":"model","match":{},"prices":{}}]`),
		provider(`"models":[{"id":"model","match":{"regex":"["},"prices":{}}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":{"cache_read_mtok":1}}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":1,"cache_read_mtok":1,"input_audio_mtok":1}}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":-1}}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1,"tiers":[{"start":-1,"price":2}]}}}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1,"tiers":[{"start":1,"price":-2}]}}}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":[]}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":[{"constraint":{"start_date":"2030-01-01"},"prices":{}}]}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":[{"prices":{}},{"prices":{}}]}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":[{}]}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":[{"constraint":{"start_date":"bad"},"prices":{}}]}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":[{"prices":{}},{"constraint":{"start_date":"0000-01-01"},"prices":{}}]}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":[{"prices":{}},{"constraint":{"start_date":"2026-01-01","tz":"UTC"},"prices":{}}]}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":[{"constraint":{"start_time":"bad","end_time":"01:00:00Z"},"prices":{}}]}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":[{"constraint":{"start_time":"00:00:00Z","end_time":"bad"},"prices":{}}]}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":[{"constraint":{},"prices":{}}]}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":"bad"}}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":null}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":1e10000}}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{}}}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1}}}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"tiers":[]}}}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1,"tiers":[{"price":2}]}}}]`),
		provider(`"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":{"base":1,"tiers":[{"start":1}]}}}]`),
		provider(`"extractors":[{"root":1,"mappings":[]}],"models":[]`),
		provider(`"extractors":[{"root":[1,"value"],"mappings":[]}],"models":[]`),
		provider(`"extractors":[{"root":[null,"value"],"mappings":[]}],"models":[]`),
	}
	for index, data := range tests {
		t.Run(strconv.Itoa(index+1), func(t *testing.T) {
			_, err := genai_prices.NewCalculatorFromJSON([]byte(data))
			if !errors.Is(err, genai_prices.ErrInvalidData) {
				t.Fatalf("got %v for %s", err, data)
			}
		})
	}
}

func newTestCalculator(t *testing.T, data string) *genai_prices.Calculator {
	t.Helper()
	calculator, err := genai_prices.NewCalculatorFromJSON([]byte(data))
	if err != nil {
		t.Fatal(err)
	}
	return calculator
}
