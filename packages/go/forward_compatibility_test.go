package genai_prices_test

import (
	"encoding/json"
	"errors"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/pydantic/genai-prices/packages/go"
)

var forwardCompatibilityWarnings = []string{
	`Unsupported match variant at providers[0].model_match for provider "future-fixture"; upgrade genai-prices for full support`,
	`Unsupported extractor variant at providers[0].extractors[1] for provider "future-fixture"; upgrade genai-prices for full support`,
	`Unsupported price variant at providers[0].models[0].prices[0].prices.cache_read_mtok for provider "future-fixture", model "future-model"; upgrade genai-prices for full support`,
	`Unsupported constraint variant at providers[0].models[0].prices[1].constraint for provider "future-fixture", model "future-model"; upgrade genai-prices for full support`,
	`Unsupported match variant at providers[0].models[1].match for provider "future-fixture", model "unsupported-model"; upgrade genai-prices for full support`,
}

func TestForwardCompatibleProjectionAndMalformedAtomicity(t *testing.T) {
	fixture := readForwardCompatibilityFixture(t)
	calculator, err := genai_prices.NewCalculatorFromJSON(fixture)
	if err != nil {
		t.Fatal(err)
	}

	extracted, err := calculator.ExtractUsage(genai_prices.ExtractRequest{
		ResponseJSON: []byte(`{"model":"future-model","usage":{"input":1000000,"output":1000000}}`),
		ProviderID:   "future-alias",
	})
	if err != nil {
		t.Fatal(err)
	}
	if extracted.ProviderID != "future-fixture" || extracted.Model != "future-model" ||
		extracted.Usage[genai_prices.UsageInputTokens] != 1_000_000 ||
		extracted.Usage[genai_prices.UsageOutputTokens] != 1_000_000 ||
		!reflect.DeepEqual(extracted.Warnings, forwardCompatibilityWarnings) {
		t.Fatalf("unexpected extraction: %#v", extracted)
	}

	usage := genai_prices.Usage{
		genai_prices.UsageInputTokens:  1_000_000,
		genai_prices.UsageOutputTokens: 1_000_000,
	}
	assertForwardPrice(t, calculator, usage, time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC), 1, 2, 3)
	assertForwardPrice(t, calculator, usage, time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC), 3, 4, 7)

	_, err = calculator.Calculate(genai_prices.PriceRequest{Usage: usage, Model: "future-model"})
	if !errors.Is(err, genai_prices.ErrProviderNotFound) {
		t.Fatalf("unsupported provider model_match was retained: %v", err)
	}
	_, err = calculator.Calculate(genai_prices.PriceRequest{
		Usage: usage, Model: "unsupported-model", ProviderID: "future-fixture",
	})
	if !errors.Is(err, genai_prices.ErrModelNotFound) {
		t.Fatalf("unsupported model match was retained: %v", err)
	}

	malformed := readMalformedCompatibilityFixture(t)
	invalidConstraint := mutateForwardCompatibilityFixture(t, fixture, func(root map[string]any) {
		provider := root["providers"].([]any)[0].(map[string]any)
		model := provider["models"].([]any)[0].(map[string]any)
		price := model["prices"].([]any)[2].(map[string]any)
		price["constraint"] = malformed["constraint"]
	})
	assertInvalidForwardReplacement(t, invalidConstraint)

	invalidExtractor := mutateForwardCompatibilityFixture(t, fixture, func(root map[string]any) {
		provider := root["providers"].([]any)[0].(map[string]any)
		provider["extractors"].([]any)[0] = malformed["extractor"]
	})
	assertInvalidForwardReplacement(t, invalidExtractor)

	assertForwardPrice(t, calculator, usage, time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC), 1, 2, 3)
}

func assertForwardPrice(
	t *testing.T,
	calculator *genai_prices.Calculator,
	usage genai_prices.Usage,
	timestamp time.Time,
	inputPrice float64,
	outputPrice float64,
	totalPrice float64,
) {
	t.Helper()
	calculation, err := calculator.Calculate(genai_prices.PriceRequest{
		Usage: usage, Model: "future-model", ProviderID: "future-alias", Timestamp: timestamp,
	})
	if err != nil {
		t.Fatal(err)
	}
	if calculation.ProviderID != "future-fixture" || calculation.ModelID != "future-model" ||
		calculation.InputPrice != inputPrice || calculation.OutputPrice != outputPrice ||
		calculation.TotalPrice != totalPrice || !reflect.DeepEqual(calculation.Warnings, forwardCompatibilityWarnings) {
		t.Fatalf("unexpected calculation: %#v", calculation)
	}
}

func assertInvalidForwardReplacement(t *testing.T, data []byte) {
	t.Helper()
	calculator, err := genai_prices.NewCalculatorFromJSON(data)
	if calculator != nil || !errors.Is(err, genai_prices.ErrInvalidData) {
		t.Fatalf("got calculator=%#v error=%v", calculator, err)
	}
}

func mutateForwardCompatibilityFixture(t *testing.T, data []byte, mutate func(map[string]any)) []byte {
	t.Helper()
	var root map[string]any
	if err := json.Unmarshal(data, &root); err != nil {
		t.Fatal(err)
	}
	mutate(root)
	mutated, err := json.Marshal(root)
	if err != nil {
		t.Fatal(err)
	}
	return mutated
}

func readForwardCompatibilityFixture(t *testing.T) []byte {
	t.Helper()
	data, err := os.ReadFile("../../tests/fixtures/forward-compatible-v3.json")
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func readMalformedCompatibilityFixture(t *testing.T) map[string]any {
	t.Helper()
	data, err := os.ReadFile("../../tests/fixtures/malformed-recognized-v3.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture map[string]any
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	return fixture
}
