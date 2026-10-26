package genai_prices_test

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/pydantic/genai-prices/packages/go"
)

func TestPriceContextContract(t *testing.T) {
	data, err := os.ReadFile("../../tests/fixtures/price_context.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Providers json.RawMessage    `json:"providers"`
		Usage     genai_prices.Usage `json:"usage"`
		Cases     []struct {
			Name      string            `json:"name"`
			Timestamp string            `json:"timestamp"`
			Context   map[string]string `json:"context"`
			Input     float64           `json:"input"`
			Output    float64           `json:"output"`
			Total     float64           `json:"total"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	calculator, err := genai_prices.NewCalculatorFromJSON(fixture.Providers)
	if err != nil {
		t.Fatal(err)
	}
	for _, test := range fixture.Cases {
		t.Run(test.Name, func(t *testing.T) {
			timestamp, err := time.Parse(time.RFC3339, test.Timestamp)
			if err != nil {
				t.Fatal(err)
			}
			result, err := calculator.Calculate(genai_prices.PriceRequest{
				Usage: fixture.Usage, Model: "context-model", ProviderID: "testing",
				Timestamp: timestamp, PriceContext: test.Context,
			})
			if err != nil {
				t.Fatal(err)
			}
			if result.InputPrice != test.Input || result.OutputPrice != test.Output || result.TotalPrice != test.Total {
				t.Fatalf("got %+v, want %v/%v/%v", result, test.Input, test.Output, test.Total)
			}
			if len(result.Warnings) != 0 {
				t.Fatalf("got warnings %v", result.Warnings)
			}
		})
	}
}

func TestOpenAIServiceTiers(t *testing.T) {
	for _, test := range []struct {
		model, tier string
		total       float64
	}{
		{"o3", "flex", 4.8125}, {"o3", "priority", 16.84375},
		{"o4-mini", "flex", 2.647}, {"o4-mini", "priority", 9.625},
		{"gpt-5-mini", "flex", 1.096875}, {"gpt-6.1-sol", "fast", 36.1},
		{"gpt-6.1-sol", "priority", 36.1}, {"gpt-6.1-terra", "flex", 4.5125},
		{"gpt-6.1-terra", "fast", 18.05}, {"gpt-6.1-terra", "priority", 18.05},
	} {
		t.Run(test.model+"/"+test.tier, func(t *testing.T) {
			result, err := genai_prices.Calculate(genai_prices.PriceRequest{
				Usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000, genai_prices.UsageCacheReadTokens: 250_000, genai_prices.UsageOutputTokens: 1_000_000},
				Model: test.model, ProviderID: "openai", Timestamp: time.Date(2026, 10, 26, 0, 0, 0, 0, time.UTC),
				PriceContext: map[string]string{"service_tier": test.tier},
			})
			if err != nil {
				t.Fatal(err)
			}
			if math.Abs(result.TotalPrice-test.total) > 1e-12 {
				t.Fatalf("got %v, want %v", result.TotalPrice, test.total)
			}
			if len(result.Warnings) != 0 {
				t.Fatalf("got warnings %v", result.Warnings)
			}
		})
	}
}

func TestBatchProcessing(t *testing.T) {
	for _, test := range []struct {
		provider, model string
		timestamp       time.Time
		total           float64
	}{
		{"openai", "o3", time.Date(2026, 10, 14, 0, 0, 0, 0, time.UTC), 4.875},
		{"anthropic", "claude-sonnet-5", time.Date(2026, 10, 14, 0, 0, 0, 0, time.UTC), 5.775},
		{"google", "gemini-4-argon", time.Date(2026, 10, 14, 0, 0, 0, 0, time.UTC), 5.7625},
		{"google", "gemini-4-argon", time.Date(2026, 12, 1, 0, 0, 0, 0, time.UTC), 11.525},
		{"groq", "openai/gpt-oss-120b", time.Date(2026, 10, 14, 0, 0, 0, 0, time.UTC), 0.375},
		{"mistral", "mistral-small-2603", time.Date(2026, 10, 14, 0, 0, 0, 0, time.UTC), 0.358125},
		{"x-ai", "grok-4.3", time.Date(2026, 10, 14, 0, 0, 0, 0, time.UTC), 5.58},
	} {
		t.Run(test.provider+"/"+test.model+"/"+test.timestamp.Format(time.DateOnly), func(t *testing.T) {
			result, err := genai_prices.Calculate(genai_prices.PriceRequest{
				Usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000, genai_prices.UsageCacheReadTokens: 250_000, genai_prices.UsageOutputTokens: 1_000_000},
				Model: test.model, ProviderID: test.provider, Timestamp: test.timestamp,
				PriceContext: map[string]string{"processing": "batch"},
			})
			if err != nil {
				t.Fatal(err)
			}
			if math.Abs(result.TotalPrice-test.total) > 1e-12 {
				t.Fatalf("got %v, want %v", result.TotalPrice, test.total)
			}
			if len(result.Warnings) != 0 {
				t.Fatalf("got warnings %v", result.Warnings)
			}
		})
	}
}

func TestOpenAIPublishedFlexRates(t *testing.T) {
	for _, test := range []struct {
		model                        string
		inputTokens, cacheReadTokens float64
		inputPrice, outputPrice      float64
	}{
		{"o4-mini", 100_000, 100_000, 0.0138, 2.2},
		{"gpt-5.4", 272_000, 272_000, 0.03536, 7.5},
		{"gpt-5.4", 272_001, 272_001, 0.06800025, 11.25},
		{"gpt-5.5-pro", 272_000, 0, 4.08, 90},
		{"gpt-5.5-pro", 272_001, 0, 4.080015, 90},
	} {
		t.Run(test.model+"/"+fmt.Sprint(test.inputTokens), func(t *testing.T) {
			result, err := genai_prices.Calculate(genai_prices.PriceRequest{
				Usage: genai_prices.Usage{
					genai_prices.UsageInputTokens:     test.inputTokens,
					genai_prices.UsageCacheReadTokens: test.cacheReadTokens,
					genai_prices.UsageOutputTokens:    1_000_000,
				},
				Model: test.model, ProviderID: "openai", Timestamp: time.Date(2026, 10, 12, 0, 0, 0, 0, time.UTC),
				PriceContext: map[string]string{"service_tier": "flex"},
			})
			if err != nil {
				t.Fatal(err)
			}
			if math.Abs(result.InputPrice-test.inputPrice) > 1e-12 || math.Abs(result.OutputPrice-test.outputPrice) > 1e-12 {
				t.Fatalf("got %v/%v, want %v/%v", result.InputPrice, result.OutputPrice, test.inputPrice, test.outputPrice)
			}
			if len(result.Warnings) != 0 {
				t.Fatalf("got warnings %v", result.Warnings)
			}
		})
	}
}

func TestInvalidPriceVariants(t *testing.T) {
	for _, variant := range []string{
		`{"when":{},"prices":{}}`, `{"when":{"service_tier":null},"prices":{}}`,
		`{"when":{"service_tier":true},"prices":{}}`, `{"when":{"service_tier":"flex"}}`,
		`{"when":{"service_tier":"flex"},"prices":{"input_mtok":-1}}`,
		`{"when":{"service_tier":"flex"},"prices":{},"constraint":{"start_date":"bad"}}`,
	} {
		t.Run(variant, func(t *testing.T) {
			_, err := genai_prices.NewCalculatorFromJSON([]byte(`[{"id":"testing","name":"Testing","api_pattern":"testing","models":[{"id":"m","match":{"equals":"m"},"prices":{"input_mtok":1},"price_variants":[` + variant + `]}]}]`))
			if err == nil {
				t.Fatal("accepted invalid variant")
			}
		})
	}
	calculator := newTestCalculator(t, `[{"id":"testing","name":"Testing","api_pattern":"testing","models":[{"id":"m","match":{"equals":"m"},"prices":{"input_mtok":1},"price_variants":[{"when":{"service_tier":"flex"},"prices":{"cache_image_read_mtok":1}}]}]}]`)
	_, err := calculator.Calculate(genai_prices.PriceRequest{Model: "m", ProviderID: "testing", PriceContext: map[string]string{"service_tier": "flex"}})
	if err == nil || !strings.Contains(err.Error(), "missing ancestor") {
		t.Fatalf("got %v", err)
	}
}

func TestFallbackProviderDoesNotInheritTierRates(t *testing.T) {
	for _, context := range []map[string]string{nil, {}, {"service_tier": "priority"}} {
		result, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000, genai_prices.UsageOutputTokens: 1_000_000},
			Model: "gpt-5", ProviderID: "azure", Timestamp: time.Date(2026, 10, 12, 0, 0, 0, 0, time.UTC),
			PriceContext: context,
		})
		if err != nil {
			t.Fatal(err)
		}
		if result.ProviderID != "azure" || result.TotalPrice != 11.25 {
			t.Fatalf("got %+v", result)
		}
		if len(result.Warnings) != 0 {
			t.Fatalf("got warnings %v", result.Warnings)
		}
	}
}
