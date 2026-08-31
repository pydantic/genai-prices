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
