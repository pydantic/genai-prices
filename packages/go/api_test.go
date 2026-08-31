package genaiprices_test

import (
	"errors"
	"math"
	"testing"
	"time"

	genaiprices "github.com/pydantic/genai-prices/packages/go"
)

func TestCalculate(t *testing.T) {
	calculation, err := genaiprices.Calculate(genaiprices.PriceRequest{
		Usage: genaiprices.Usage{
			genaiprices.UsageInputTokens:  1_000,
			genaiprices.UsageOutputTokens: 100,
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
	calculation, err := genaiprices.Calculate(genaiprices.PriceRequest{
		Usage: genaiprices.Usage{
			genaiprices.UsageInputTokens: 1,
			"unknown_tokens":             2,
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
		request genaiprices.PriceRequest
		target  error
	}{
		{name: "missing model", request: genaiprices.PriceRequest{}, target: genaiprices.ErrModelNotFound},
		{
			name: "conflicting provider selectors",
			request: genaiprices.PriceRequest{
				Model:          "gpt-5",
				ProviderID:     "openai",
				ProviderAPIURL: "https://api.openai.com",
			},
			target: genaiprices.ErrInvalidUsage,
		},
		{
			name:    "unknown provider",
			request: genaiprices.PriceRequest{Model: "gpt-5", ProviderID: "missing"},
			target:  genaiprices.ErrProviderNotFound,
		},
		{
			name:    "unknown model",
			request: genaiprices.PriceRequest{Model: "missing", ProviderID: "openai"},
			target:  genaiprices.ErrModelNotFound,
		},
		{
			name: "negative usage",
			request: genaiprices.PriceRequest{
				Usage:      genaiprices.Usage{genaiprices.UsageInputTokens: -1},
				Model:      "gpt-5",
				ProviderID: "openai",
			},
			target: genaiprices.ErrInvalidUsage,
		},
		{
			name: "non-finite usage",
			request: genaiprices.PriceRequest{
				Usage:      genaiprices.Usage{genaiprices.UsageInputTokens: math.Inf(1)},
				Model:      "gpt-5",
				ProviderID: "openai",
			},
			target: genaiprices.ErrInvalidUsage,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := genaiprices.Calculate(test.request)
			if !errors.Is(err, test.target) {
				t.Fatalf("got %v, want %v", err, test.target)
			}
		})
	}
}

func TestNewCalculatorFromJSON(t *testing.T) {
	calculator, err := genaiprices.NewCalculatorFromJSON([]byte(`[
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
	calculation, err := calculator.Calculate(genaiprices.PriceRequest{
		Usage: genaiprices.Usage{
			genaiprices.UsageInputTokens:  1_000_000,
			genaiprices.UsageOutputTokens: 500_000,
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
		_, err := genaiprices.NewCalculatorFromJSON(data)
		if !errors.Is(err, genaiprices.ErrInvalidData) {
			t.Fatalf("got %v", err)
		}
	}
}
