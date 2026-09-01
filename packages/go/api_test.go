package genai_prices_test

import (
	"errors"
	"math"
	"testing"
	"time"

	"github.com/pydantic/genai-prices/packages/go"
)

func TestCalculate(t *testing.T) {
	calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{
			genai_prices.UsageInputTokens:  1_000,
			genai_prices.UsageOutputTokens: 100,
		},
		Model:      "gpt-5",
		ProviderID: "openai",
		Timestamp:  time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatal(err)
	}
	if calculation.ProviderID != "openai" || calculation.ModelID != "gpt-5" {
		t.Fatalf("unexpected match: %#v", calculation)
	}
	if calculation.TotalPrice <= 0 {
		t.Fatalf("expected a positive price, got %g", calculation.TotalPrice)
	}
}

func TestOpenAILongContextBoundary(t *testing.T) {
	tests := []struct {
		model    string
		baseRate float64
		longRate float64
	}{
		{model: "gpt-5.4", baseRate: 2.5, longRate: 5},
		{model: "gpt-5.4-pro", baseRate: 30, longRate: 60},
		{model: "gpt-5.5", baseRate: 5, longRate: 10},
		{model: "gpt-5.5-pro", baseRate: 30, longRate: 60},
		{model: "gpt-5.6-luna", baseRate: 0.2, longRate: 0.4},
		{model: "gpt-5.6-sol", baseRate: 4, longRate: 8},
		{model: "gpt-5.6-terra", baseRate: 2, longRate: 4},
	}
	for _, test := range tests {
		t.Run(test.model, func(t *testing.T) {
			for _, boundary := range []struct {
				tokens float64
				rate   float64
			}{
				{tokens: 271_999, rate: test.baseRate},
				{tokens: 272_000, rate: test.longRate},
			} {
				calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
					Usage:      genai_prices.Usage{genai_prices.UsageInputTokens: boundary.tokens},
					Model:      test.model,
					ProviderID: "openai",
				})
				if err != nil {
					t.Fatal(err)
				}
				want := boundary.tokens * boundary.rate / 1_000_000
				if math.Abs(calculation.InputPrice-want) > 1e-12 {
					t.Fatalf("%g tokens: got %g, want %g", boundary.tokens, calculation.InputPrice, want)
				}
			}
		})
	}
}

func TestCalculateTreatsWhitespaceProviderIDAsAbsent(t *testing.T) {
	calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
		Usage:          genai_prices.Usage{genai_prices.UsageInputTokens: 1_000},
		Model:          "gpt-5",
		ProviderID:     "  ",
		ProviderAPIURL: "https://api.openai.com",
	})
	if err != nil {
		t.Fatal(err)
	}
	if calculation.ProviderID != "openai" {
		t.Fatalf("got provider %q", calculation.ProviderID)
	}
}

func TestCalculateReportsUnsupportedUsage(t *testing.T) {
	calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{
			genai_prices.UsageInputTokens: 1,
			"unknown_tokens":              2,
		},
		Model:      "gpt-5",
		ProviderID: "openai",
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(calculation.Warnings) != 1 {
		t.Fatalf("unexpected warnings: %v", calculation.Warnings)
	}
}

func TestCalculateErrors(t *testing.T) {
	tests := []struct {
		name    string
		request genai_prices.PriceRequest
		target  error
	}{
		{name: "missing model", request: genai_prices.PriceRequest{}, target: genai_prices.ErrModelNotFound},
		{
			name: "conflicting provider selectors",
			request: genai_prices.PriceRequest{
				Model:          "gpt-5",
				ProviderID:     "openai",
				ProviderAPIURL: "https://api.openai.com",
			},
			target: genai_prices.ErrInvalidUsage,
		},
		{
			name:    "unknown provider",
			request: genai_prices.PriceRequest{Model: "gpt-5", ProviderID: "missing"},
			target:  genai_prices.ErrProviderNotFound,
		},
		{
			name:    "unknown model",
			request: genai_prices.PriceRequest{Model: "missing", ProviderID: "openai"},
			target:  genai_prices.ErrModelNotFound,
		},
		{
			name: "negative usage",
			request: genai_prices.PriceRequest{
				Usage:      genai_prices.Usage{genai_prices.UsageInputTokens: -1},
				Model:      "gpt-5",
				ProviderID: "openai",
			},
			target: genai_prices.ErrInvalidUsage,
		},
		{
			name: "non-finite usage",
			request: genai_prices.PriceRequest{
				Usage:      genai_prices.Usage{genai_prices.UsageInputTokens: math.Inf(1)},
				Model:      "gpt-5",
				ProviderID: "openai",
			},
			target: genai_prices.ErrInvalidUsage,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := genai_prices.Calculate(test.request)
			if !errors.Is(err, test.target) {
				t.Fatalf("got %v, want %v", err, test.target)
			}
		})
	}
}

func TestCalculateRejectsPriceOverflow(t *testing.T) {
	calculator, err := genai_prices.NewCalculatorFromJSON([]byte(`[
		{
			"id":"testing","name":"Testing","api_pattern":"testing",
			"models":[{"id":"model","match":{"equals":"model"},"prices":{"output_mtok":2}}]
		}
	]`))
	if err != nil {
		t.Fatal(err)
	}
	_, err = calculator.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{genai_prices.UsageOutputTokens: math.MaxFloat64}, Model: "model", ProviderID: "testing",
	})
	if !errors.Is(err, genai_prices.ErrInvalidUsage) {
		t.Fatalf("got %v", err)
	}
}

func TestDuplicatePricesUsesLastValue(t *testing.T) {
	calculator, err := genai_prices.NewCalculatorFromJSON([]byte(`[
		{
			"id":"testing","name":"Testing","api_pattern":"testing",
			"models":[{
				"id":"model","match":{"equals":"model"},
				"prices":[{"prices":{"input_mtok":2}}],
				"prices":{"input_mtok":1}
			}]
		}
	]`))
	if err != nil {
		t.Fatal(err)
	}
	calculation, err := calculator.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000}, Model: "model", ProviderID: "testing",
	})
	if err != nil {
		t.Fatal(err)
	}
	if calculation.TotalPrice != 1 {
		t.Fatalf("got %g", calculation.TotalPrice)
	}
}

func TestNewCalculatorFromJSON(t *testing.T) {
	calculator, err := genai_prices.NewCalculatorFromJSON([]byte(`[
		{
			"id": "testing",
			"name": "Testing",
			"api_pattern": "https://testing\\.example",
			"model_match": {"starts_with": "test-"},
			"models": [{
				"id": "test-model",
				"match": {"equals": "test-model"},
				"prices": {"input_mtok": 2, "output_mtok": 4}
			}]
		}
	]`))
	if err != nil {
		t.Fatal(err)
	}
	calculation, err := calculator.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{
			genai_prices.UsageInputTokens:  1_000_000,
			genai_prices.UsageOutputTokens: 500_000,
		},
		Model: "test-model",
	})
	if err != nil {
		t.Fatal(err)
	}
	if calculation.InputPrice != 2 || calculation.OutputPrice != 2 || calculation.TotalPrice != 4 {
		t.Fatalf("unexpected calculation: %#v", calculation)
	}
}

func TestNewCalculatorFromJSONRejectsInvalidData(t *testing.T) {
	for _, data := range [][]byte{[]byte(`{}`), []byte(`null`), []byte(`not JSON`)} {
		_, err := genai_prices.NewCalculatorFromJSON(data)
		if !errors.Is(err, genai_prices.ErrInvalidData) {
			t.Fatalf("got %v", err)
		}
	}
}

// Fable 5.1 caches reads at 0.025x base input; Fable 5 at the usual 0.1x. The Fable 5
// records match by prefix, so a loose clause silently prices Fable 5.1 cache reads 4x
// too high instead of failing.
func TestClaudeFable51DoesNotUseFable5Prices(t *testing.T) {
	tests := []struct {
		providerID    string
		fable5        string
		fable51       string
		wantCacheRead float64
	}{
		{"anthropic", "claude-fable-5", "claude-fable-5-1", 0.25},
		{"anthropic", "claude-fable-5-20260901", "claude-fable-5-1-20260901", 0.25},
		{"google", "claude-fable-5", "claude-fable-5-1", 0.25},
		{"google", "claude-fable-5@20260901", "claude-fable-5-1@20260901", 0.25},
		{"aws", "global.anthropic.claude-fable-5-v1:0", "global.anthropic.claude-fable-5-1-v1:0", 0.25},
		{"aws", "us.anthropic.claude-fable-5-v1:0", "us.anthropic.claude-fable-5-1-v1:0", 0.275},
		{"openrouter", "anthropic/claude-fable-5", "anthropic/claude-fable-5.1", 0.25},
	}
	usage := genai_prices.Usage{
		genai_prices.UsageInputTokens:     1_000_000,
		genai_prices.UsageCacheReadTokens: 1_000_000,
	}
	for _, test := range tests {
		t.Run(test.providerID+"/"+test.fable51, func(t *testing.T) {
			fable5, err := genai_prices.Calculate(genai_prices.PriceRequest{
				Usage: usage, Model: test.fable5, ProviderID: test.providerID,
			})
			if err != nil {
				t.Fatal(err)
			}
			fable51, err := genai_prices.Calculate(genai_prices.PriceRequest{
				Usage: usage, Model: test.fable51, ProviderID: test.providerID,
			})
			if err != nil {
				t.Fatal(err)
			}
			if fable5.ModelID == fable51.ModelID {
				t.Fatalf("Fable 5.1 resolved to the Fable 5 record %q", fable51.ModelID)
			}
			if math.Abs(fable51.TotalPrice-test.wantCacheRead) > 1e-9 {
				t.Fatalf("got cache-read price %g, want %g", fable51.TotalPrice, test.wantCacheRead)
			}
			if math.Abs(fable51.TotalPrice*4-fable5.TotalPrice) > 1e-9 {
				t.Fatalf("got %g for Fable 5.1 and %g for Fable 5, want a 4x split", fable51.TotalPrice, fable5.TotalPrice)
			}
		})
	}
}

// OpenRouter's family-level alias had not moved to 5.1 when 5.1 was added.
func TestOpenRouterClaudeFableLatestStillPointsAtFable5(t *testing.T) {
	calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{
			genai_prices.UsageInputTokens:     1_000_000,
			genai_prices.UsageCacheReadTokens: 1_000_000,
		},
		Model:      "~anthropic/claude-fable-latest",
		ProviderID: "openrouter",
	})
	if err != nil {
		t.Fatal(err)
	}
	if math.Abs(calculation.TotalPrice-1) > 1e-9 {
		t.Fatalf("got %g, want 1", calculation.TotalPrice)
	}
}
