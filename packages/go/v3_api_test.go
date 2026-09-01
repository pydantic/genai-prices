package genai_prices_test

import (
	"encoding/json"
	"errors"
	"os"
	"strings"
	"testing"

	"github.com/pydantic/genai-prices/packages/go"
)

func TestRemoteDataURLUsesWrappedV3Feed(t *testing.T) {
	if genai_prices.RemoteDataURL != "https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/new_data/v3/data.json" {
		t.Fatalf("unexpected remote data URL: %s", genai_prices.RemoteDataURL)
	}
}

func TestNewCalculatorFromWrappedV3Data(t *testing.T) {
	calculator, err := genai_prices.NewCalculatorFromJSON(readV3Data(t))
	if err != nil {
		t.Fatal(err)
	}
	calculation, err := calculator.Calculate(genai_prices.PriceRequest{
		Usage:      genai_prices.Usage{genai_prices.UsageInputTokens: 1_000},
		Model:      "gpt-5",
		ProviderID: "openai",
	})
	if err != nil {
		t.Fatal(err)
	}
	if calculation.ProviderID != "openai" || calculation.ModelID != "gpt-5" || len(calculation.Warnings) != 0 {
		t.Fatalf("unexpected calculation: %#v", calculation)
	}
}

func TestWrappedCompatibilityWarningsReachCalculationAndExtraction(t *testing.T) {
	wrapper := readRawV3Wrapper(t)
	wrapper.Providers = json.RawMessage(`[
		{
			"id":"testing","name":"Testing","api_pattern":"testing","provider_match":{"future_match":"testing"},
			"extractors":[{"root":"usage","mappings":[{"path":"input","dest":"input_tokens"}]}],
			"models":[{"id":"model","match":{"equals":"model"},"prices":{"input_mtok":2}}]
		}
	]`)
	data, err := json.Marshal(wrapper)
	if err != nil {
		t.Fatal(err)
	}
	calculator, err := genai_prices.NewCalculatorFromJSON(data)
	if err != nil {
		t.Fatal(err)
	}

	calculation, err := calculator.Calculate(genai_prices.PriceRequest{
		Usage:      genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000},
		Model:      "model",
		ProviderID: "testing",
	})
	if err != nil {
		t.Fatal(err)
	}
	assertCompatibilityWarning(t, calculation.Warnings)
	calculation.Warnings[0] = "mutated by caller"
	repeated, err := calculator.Calculate(genai_prices.PriceRequest{Model: "model", ProviderID: "testing"})
	if err != nil {
		t.Fatal(err)
	}
	assertCompatibilityWarning(t, repeated.Warnings)

	extracted, err := calculator.ExtractUsage(genai_prices.ExtractRequest{
		ResponseJSON: []byte(`{"model":"model","usage":{"input":3}}`),
		ProviderID:   "testing",
	})
	if err != nil {
		t.Fatal(err)
	}
	if extracted.Usage[genai_prices.UsageInputTokens] != 3 {
		t.Fatalf("unexpected usage: %#v", extracted.Usage)
	}
	assertCompatibilityWarning(t, extracted.Warnings)
}

func TestWrappedCalculatorSupportsRemoteOnlyUsageKey(t *testing.T) {
	data, err := os.ReadFile("../../tests/fixtures/remote-unit-v3.json")
	if err != nil {
		t.Fatal(err)
	}
	calculator, err := genai_prices.NewCalculatorFromJSON(data)
	if err != nil {
		t.Fatal(err)
	}

	extracted, err := calculator.ExtractUsage(genai_prices.ExtractRequest{
		ResponseJSON: []byte(`{"model":"remote-model","usage":{"events":500}}`),
		ProviderID:   "remote-alias",
	})
	if err != nil {
		t.Fatal(err)
	}
	remoteEvents := genai_prices.UsageKey("remote_events")
	if extracted.Usage[remoteEvents] != 500 || extracted.ProviderID != "remote-fixture" ||
		extracted.Model != "remote-model" || len(extracted.Warnings) != 0 {
		t.Fatalf("unexpected extraction: %#v", extracted)
	}
	calculation, err := calculator.Calculate(genai_prices.PriceRequest{
		Usage:      genai_prices.Usage{remoteEvents: 500},
		Model:      "remote-model",
		ProviderID: "remote-alias",
	})
	if err != nil {
		t.Fatal(err)
	}
	if calculation.ProviderID != "remote-fixture" || calculation.ModelID != "remote-model" ||
		calculation.InputPrice != 1 || calculation.OutputPrice != 0 || calculation.TotalPrice != 1 ||
		len(calculation.Warnings) != 0 {
		t.Fatalf("unexpected calculation: %#v", calculation)
	}

	wrapper := readRawV3WrapperFromData(t, data)
	wrapper.Units = json.RawMessage(`[]`)
	invalid, err := json.Marshal(wrapper)
	if err != nil {
		t.Fatal(err)
	}
	invalidCalculator, err := genai_prices.NewCalculatorFromJSON(invalid)
	if invalidCalculator != nil || !errors.Is(err, genai_prices.ErrInvalidData) {
		t.Fatalf("got calculator=%#v error=%v", invalidCalculator, err)
	}
	repeated, err := calculator.Calculate(genai_prices.PriceRequest{
		Usage:      genai_prices.Usage{remoteEvents: 500},
		Model:      "remote-model",
		ProviderID: "remote-alias",
	})
	if err != nil || repeated.TotalPrice != 1 {
		t.Fatalf("original calculator changed: calculation=%#v error=%v", repeated, err)
	}
}

func TestWrappedConstructionFailureReturnsNilAndLeavesBundledCalculatorIndependent(t *testing.T) {
	before, err := genai_prices.Calculate(genai_prices.PriceRequest{
		Usage:      genai_prices.Usage{genai_prices.UsageInputTokens: 1_000},
		Model:      "gpt-5",
		ProviderID: "openai",
	})
	if err != nil {
		t.Fatal(err)
	}

	for _, data := range [][]byte{
		[]byte(`{}`),
		[]byte(`{"units":[],"providers":[]}`),
		[]byte(`{"units":{},"providers":[]}`),
	} {
		calculator, err := genai_prices.NewCalculatorFromJSON(data)
		if calculator != nil || !errors.Is(err, genai_prices.ErrInvalidData) {
			t.Fatalf("got calculator=%#v error=%v", calculator, err)
		}
	}

	after, err := genai_prices.Calculate(genai_prices.PriceRequest{
		Usage:      genai_prices.Usage{genai_prices.UsageInputTokens: 1_000},
		Model:      "gpt-5",
		ProviderID: "openai",
	})
	if err != nil {
		t.Fatal(err)
	}
	if before.TotalPrice != after.TotalPrice || len(after.Warnings) != 0 {
		t.Fatalf("bundled calculator changed: before=%#v after=%#v", before, after)
	}
}

func TestLegacyCalculatorRetainsExtraMemberAndUnknownPriceTiming(t *testing.T) {
	calculator, err := genai_prices.NewCalculatorFromJSON([]byte(`[
		{
			"id":"testing","name":"Testing","api_pattern":"testing","future_provider":true,
			"models":[{
				"id":"model","match":{"equals":"model","future_match":true},"future_model":true,
				"prices":{"input_mtok":2,"future_price":7}
			}]
		}
	]`))
	if err != nil {
		t.Fatal(err)
	}
	calculation, err := calculator.Calculate(genai_prices.PriceRequest{
		Usage:      genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000},
		Model:      "model",
		ProviderID: "testing",
	})
	if err != nil {
		t.Fatal(err)
	}
	if calculation.TotalPrice != 2 || len(calculation.Warnings) != 1 || !strings.Contains(calculation.Warnings[0], "future_price") {
		t.Fatalf("unexpected legacy calculation: %#v", calculation)
	}
}

type rawV3Wrapper struct {
	Providers json.RawMessage `json:"providers"`
	Units     json.RawMessage `json:"units"`
}

func readRawV3Wrapper(t *testing.T) rawV3Wrapper {
	t.Helper()
	return readRawV3WrapperFromData(t, readV3Data(t))
}

func readRawV3WrapperFromData(t *testing.T, data []byte) rawV3Wrapper {
	t.Helper()
	var wrapper rawV3Wrapper
	if err := json.Unmarshal(data, &wrapper); err != nil {
		t.Fatal(err)
	}
	return wrapper
}

func readV3Data(t *testing.T) []byte {
	t.Helper()
	data, err := os.ReadFile("../../prices/new_data/v3/data.json")
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func assertCompatibilityWarning(t *testing.T, warnings []string) {
	t.Helper()
	if len(warnings) != 1 || !strings.Contains(warnings[0], "Unsupported match variant at providers[0].provider_match") {
		t.Fatalf("unexpected warnings: %v", warnings)
	}
}
