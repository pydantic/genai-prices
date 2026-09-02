package genai_prices

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestProjectConstraintVariants(t *testing.T) {
	tests := []struct {
		name      string
		data      string
		expected  string
		supported bool
	}{
		{name: "non-object", data: `null`, expected: `null`, supported: true},
		{name: "non-string type", data: `{"type":[]}`, expected: `{"type":[]}`, supported: true},
		{
			name:      "recognized type",
			data:      `{"future":true,"start_date":"2026-01-01","type":"start_date"}`,
			expected:  `{"start_date":"2026-01-01","type":"start_date"}`,
			supported: true,
		},
		{name: "legacy end time", data: `{"end_time":"12:00"}`, expected: `{"end_time":"12:00"}`, supported: true},
		{name: "empty object", data: `{}`, supported: false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			projected, supported, err := projectConstraint(json.RawMessage(test.data))
			if err != nil {
				t.Fatal(err)
			}
			if supported != test.supported || string(projected) != test.expected {
				t.Fatalf("got (%s, %v), want (%s, %v)", projected, supported, test.expected, test.supported)
			}
		})
	}
}

func TestDecodeWrappedProvidersDefaultsMetadataConstraintsAndExtensions(t *testing.T) {
	decoded, err := decodeWrappedProviders(json.RawMessage(`[
		{
			"id":"testing","name":"Testing","api_pattern":"testing","description":"provider description",
			"price_comments":"provider comments","pricing_urls":["https://example.com/pricing"],
			"fallback_model_providers":["fallback"],"future_provider":true,
			"provider_match":{"equals":"testing","future_match":true},
			"extractors":[{
				"root":["items",{"type":"array-match","field":"kind","match":{"equals":"usage","future_match":true},"future_path":true},"usage"],
				"future_extractor":true,
				"mappings":[
					{"path":"input","dest":"input_tokens","future_mapping":true},
					{"path":"output","dest":"output_tokens","required":false}
				]
			}],
			"models":[{
				"id":"model","name":"Model","description":"model description","context_window":999999999999999999999999,
				"price_comments":"model comments","deprecated":false,"future_model":true,
				"match":{"equals":"model","future_match":true},
				"prices":[
					{"prices":{"input_mtok":{"base":1,"tiers":[{"start":100,"price":2,"future_tier":true}],"future_tiered":true},"output_mtok":2},"future_conditional":true},
					{"constraint":{"start_date":"2025-01-01","future_constraint":true},"prices":{"input_mtok":3,"output_mtok":4}},
					{"constraint":{"start_time":"08:00:00Z","end_time":"16:00:00Z"},"prices":{"input_mtok":5,"output_mtok":6}}
				]
			}]
		}
	]`), newUnitRegistry(bundledUnits, bundledUnitOrder))
	if err != nil {
		t.Fatal(err)
	}
	if len(decoded.CompatibilityWarnings) != 0 || len(decoded.Values) != 1 {
		t.Fatalf("unexpected decode: %#v", decoded)
	}
	providerValue := decoded.Values[0]
	if len(providerValue.Extractors) != 1 || providerValue.Extractors[0].APIFlavor != "default" {
		t.Fatalf("unexpected extractors: %#v", providerValue.Extractors)
	}
	extractor := providerValue.Extractors[0]
	if dottedPath(extractor.ModelPath) != "model" || !extractor.Mappings[0].Required || extractor.Mappings[1].Required {
		t.Fatalf("defaults not applied: %#v", extractor)
	}
	if len(providerValue.Models) != 1 || len(providerValue.Models[0].Prices.conditional) != 3 {
		t.Fatalf("unexpected models: %#v", providerValue.Models)
	}
	if providerValue.Models[0].Prices.conditional[1].Constraint.StartDate != "2025-01-01" {
		t.Fatalf("start-date constraint not retained: %#v", providerValue.Models[0].Prices.conditional[1].Constraint)
	}
	if providerValue.Models[0].Prices.conditional[2].Constraint.StartTime != "08:00:00Z" {
		t.Fatalf("time constraint not retained: %#v", providerValue.Models[0].Prices.conditional[2].Constraint)
	}
}

func TestDecodeWrappedProvidersRetainsExplicitExtractorDefaults(t *testing.T) {
	decoded, err := decodeWrappedProviders(json.RawMessage(`[
		{
			"id":"testing","name":"Testing","api_pattern":"testing",
			"extractors":[{
				"api_flavor":"chat","root":"usage","model_path":"response_model",
				"mappings":[{"path":"input","dest":"input_tokens","required":false}]
			}],
			"models":[]
		}
	]`), newUnitRegistry(bundledUnits, bundledUnitOrder))
	if err != nil {
		t.Fatal(err)
	}
	extractor := decoded.Values[0].Extractors[0]
	if extractor.APIFlavor != "chat" || dottedPath(extractor.ModelPath) != "response_model" || extractor.Mappings[0].Required {
		t.Fatalf("explicit values changed: %#v", extractor)
	}
}

func TestDecodeWrappedProvidersProjectsUnsupportedCapabilitiesAndRetainsSiblings(t *testing.T) {
	decoded, err := decodeWrappedProviders(json.RawMessage(`[
		{
			"id":"testing","name":"Testing","api_pattern":"testing","provider_match":{"future_match":"testing"},
			"extractors":[
				{"type":"future-extractor","config":{}},
				{"root":{"type":"future-path"},"mappings":[]},
				{"root":"usage","mappings":[
					{"path":[{"type":"future-path"}],"dest":"input_tokens"},
					{"future_mapping":true},
					{"path":"input","dest":"input_tokens"}
				]}
			],
			"models":[
				{"id":"future-model","match":{"future_match":"model"},"prices":{"input_mtok":99}},
				{"id":"model","match":{"equals":"model"},"prices":[
					{"prices":{"input_mtok":1,"future_price":{"type":"future-price"}}},
					{"constraint":{"type":"future-constraint"},"prices":{"input_mtok":2}}
				]}
			]
		}
	]`), newUnitRegistry(bundledUnits, bundledUnitOrder))
	if err != nil {
		t.Fatal(err)
	}
	providerValue := decoded.Values[0]
	if providerValue.ProviderMatch != nil || len(providerValue.Extractors) != 1 || len(providerValue.Extractors[0].Mappings) != 1 {
		t.Fatalf("extractor siblings not retained: %#v", providerValue)
	}
	if len(providerValue.Models) != 1 || len(providerValue.Models[0].Prices.conditional) != 1 {
		t.Fatalf("model siblings not retained: %#v", providerValue.Models)
	}
	if _, found := providerValue.Models[0].Prices.conditional[0].Prices["future_price"]; found {
		t.Fatal("unsupported price was retained")
	}
	warningKinds := make([]string, len(decoded.CompatibilityWarnings))
	for index, warning := range decoded.CompatibilityWarnings {
		warningKinds[index] = strings.Split(warning, " for ")[0]
	}
	want := []string{
		"Unsupported match variant at providers[0].provider_match",
		"Unsupported extractor variant at providers[0].extractors[0]",
		"Unsupported extractor variant at providers[0].extractors[1].root",
		"Unsupported extractor mapping variant at providers[0].extractors[2].mappings[0].path",
		"Unsupported extractor mapping variant at providers[0].extractors[2].mappings[1]",
		"Unsupported match variant at providers[0].models[0].match",
		"Unsupported price variant at providers[0].models[1].prices[0].prices.future_price",
		"Unsupported constraint variant at providers[0].models[1].prices[1].constraint",
	}
	if strings.Join(warningKinds, "\n") != strings.Join(want, "\n") {
		t.Fatalf("unexpected warnings:\n%s", strings.Join(decoded.CompatibilityWarnings, "\n"))
	}
}

func TestDecodeWrappedProvidersDropsEmptyProjectedPrices(t *testing.T) {
	decoded, err := decodeWrappedProviders(json.RawMessage(`[
		{
			"id":"testing","name":"Testing","api_pattern":"testing",
			"models":[
				{"id":"empty","match":{"equals":"empty"},"prices":{"input_mtok":{"type":"future-price"}}},
				{"id":"fallback","match":{"equals":"fallback"},"prices":[
					{"prices":{"input_mtok":1}},
					{"constraint":{"start_date":"2026-01-01"},"prices":{"input_mtok":{"type":"future-price"}}}
				]}
			]
		}
	]`), newUnitRegistry(bundledUnits, bundledUnitOrder))
	if err != nil {
		t.Fatal(err)
	}
	models := decoded.Values[0].Models
	if len(models) != 1 || models[0].ID != "fallback" || len(models[0].Prices.conditional) != 1 {
		t.Fatalf("unexpected projected models: %#v", models)
	}
	if models[0].Prices.conditional[0].Prices["input_mtok"].base != 1 {
		t.Fatalf("fallback price was not retained: %#v", models[0].Prices)
	}
}

func TestDecodeWrappedProvidersDropsExtractorWithoutUsableMappings(t *testing.T) {
	decoded, err := decodeWrappedProviders(json.RawMessage(`[
		{
			"id":"testing","name":"Testing","api_pattern":"testing",
			"extractors":[{"root":"usage","mappings":[{"path":[{"type":"future-path"}],"dest":"input_tokens"}]}],
			"models":[]
		}
	]`), newUnitRegistry(bundledUnits, bundledUnitOrder))
	if err != nil {
		t.Fatal(err)
	}
	if len(decoded.Values[0].Extractors) != 0 {
		t.Fatalf("unsupported extractor was retained: %#v", decoded.Values[0].Extractors)
	}
}

func TestDecodeWrappedProvidersRejectsMalformedRecognizedData(t *testing.T) {
	tests := []struct {
		name    string
		data    string
		message string
	}{
		{name: "provider", data: `[3]`, message: "providers[0] must be an object"},
		{name: "missing models", data: `[{"id":"testing","name":"Testing","api_pattern":"testing"}]`, message: ".models is required"},
		{name: "metadata", data: `[{"id":"testing","name":"Testing","api_pattern":"testing","description":null,"models":[]}]`, message: ".description must be a string"},
		{name: "metadata array item", data: `[{"id":"testing","name":"Testing","api_pattern":"testing","fallback_model_providers":[null],"models":[]}]`, message: ".fallback_model_providers must be an array of strings"},
		{name: "model metadata", data: providerWithModel(`"context_window":1.5,`), message: ".context_window must be an integer"},
		{name: "extractor requirement", data: providerWithExtractor(`{"mappings":[]}`), message: "requires root and mappings"},
		{name: "mapping requirement", data: providerWithExtractor(`{"root":"usage","mappings":[{"path":"input"}]}`), message: "requires path and dest"},
		{name: "extract path", data: providerWithExtractor(`{"root":3,"mappings":[]}`), message: "extract path must be a string or array"},
		{name: "match value", data: providerWithModel(`"match":3,`, true), message: "match must be an object"},
		{name: "multiple match operations", data: providerWithModel(`"match":{"equals":"model","contains":"model"},`, true), message: "exactly one operation"},
		{name: "constraint", data: providerWithPrices(`[{"prices":{"input_mtok":1}},{"constraint":{"start_date":"bad"},"prices":{"input_mtok":2}}]`), message: "start-date"},
		{name: "tiered price", data: providerWithPrices(`{"input_mtok":{"tiers":[]}}`), message: "must contain base and tiers"},
	}
	registry := newUnitRegistry(bundledUnits, bundledUnitOrder)
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := decodeWrappedProviders(json.RawMessage(test.data), registry)
			if err == nil || !strings.Contains(err.Error(), test.message) {
				t.Fatalf("got %v, want error containing %q", err, test.message)
			}
		})
	}
}

func TestDecodeWrappedProvidersEagerValidation(t *testing.T) {
	tests := []struct {
		name    string
		data    string
		message string
	}{
		{name: "price", data: providerWithPrices(`{"input_mtok":-1}`), message: "finite non-negative"},
		{name: "coverage", data: providerWithPrices(`{"cache_read_mtok":1}`), message: "missing ancestor price key input_mtok"},
		{name: "destination", data: providerWithExtractor(`{"root":"usage","mappings":[{"path":"future","dest":"future_events"}]}`), message: "unknown destination"},
	}
	registry := newUnitRegistry(bundledUnits, bundledUnitOrder)
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := decodeWrappedProviders(json.RawMessage(test.data), registry)
			if err == nil || !strings.Contains(err.Error(), test.message) {
				t.Fatalf("got %v, want error containing %q", err, test.message)
			}
		})
	}
}

func TestDecodeLegacyProvidersKeepsSeparateToleranceAndDefaults(t *testing.T) {
	registry := newUnitRegistry(bundledUnits, bundledUnitOrder)
	decoded, err := decodeLegacyProviders(json.RawMessage(`[
		{
			"id":"testing","name":"Testing","api_pattern":"testing","description":null,"pricing_urls":1,"future_provider":true,
			"extractors":[{"root":"usage","mappings":[{"path":"future","dest":"future_events"}]}],
			"models":[]
		}
	]`), registry)
	if err != nil {
		t.Fatal(err)
	}
	extractor := decoded.Values[0].Extractors[0]
	if extractor.APIFlavor != "default" || dottedPath(extractor.ModelPath) != "model" || !extractor.Mappings[0].Required {
		t.Fatalf("legacy defaults not applied: %#v", extractor)
	}
	if len(decoded.CompatibilityWarnings) != 0 {
		t.Fatalf("legacy warnings changed: %v", decoded.CompatibilityWarnings)
	}

	_, err = decodeLegacyProviders(json.RawMessage(`[
		{"id":"testing","name":"Testing","api_pattern":"testing","provider_match":{"future_match":"testing"},"models":[]}
	]`), registry)
	if err == nil || !strings.Contains(err.Error(), "exactly one operation") {
		t.Fatalf("legacy unsupported structure should remain an error, got %v", err)
	}
}

func providerWithExtractor(extractor string) string {
	return `[{"id":"testing","name":"Testing","api_pattern":"testing","extractors":[` + extractor + `],"models":[]}]`
}

func providerWithModel(modelFields string, replaceMatch ...bool) string {
	match := `"match":{"equals":"model"},`
	if len(replaceMatch) > 0 && replaceMatch[0] {
		match = ""
	}
	return `[{"id":"testing","name":"Testing","api_pattern":"testing","models":[{"id":"model",` + match + modelFields + `"prices":{"input_mtok":1}}]}]`
}

func providerWithPrices(prices string) string {
	return `[{"id":"testing","name":"Testing","api_pattern":"testing","models":[{"id":"model","match":{"equals":"model"},"prices":` + prices + `}]}]`
}
