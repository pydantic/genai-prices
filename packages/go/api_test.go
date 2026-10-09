package genai_prices_test

import (
	"errors"
	"maps"
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
		{model: "gpt-6.1-sol", baseRate: 2, longRate: 4},
	}
	for _, test := range tests {
		t.Run(test.model, func(t *testing.T) {
			for _, boundary := range []struct {
				tokens float64
				rate   float64
			}{
				{tokens: 272_000, rate: test.baseRate},
				{tokens: 272_001, rate: test.longRate},
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

// Bedrock's Fable inference profile ids carry no `-v1:0` suffix; geographic ones take the regional rate.
func TestAWSClaudeFableInferenceProfileIDs(t *testing.T) {
	tests := []struct {
		model     string
		modelID   string
		wantTotal float64
	}{
		{"us.anthropic.claude-fable-5", "regional.anthropic.claude-fable-5-v1:0", 80.85},
		{"eu.anthropic.claude-fable-5", "regional.anthropic.claude-fable-5-v1:0", 80.85},
		{"au.anthropic.claude-fable-5", "regional.anthropic.claude-fable-5-v1:0", 80.85},
		{"us.anthropic.claude-fable-5-v1:0", "regional.anthropic.claude-fable-5-v1:0", 80.85},
		{"anthropic.claude-fable-5", "regional.anthropic.claude-fable-5-v1:0", 80.85},
		{"global.anthropic.claude-fable-5", "global.anthropic.claude-fable-5-v1:0", 73.5},
		{"global.anthropic.claude-fable-5-v1:0", "global.anthropic.claude-fable-5-v1:0", 73.5},
		{"us.anthropic.claude-fable-5-1", "regional.anthropic.claude-fable-5-1-v1:0", 80.025},
		{"us.anthropic.claude-fable-5-1-v1:0", "regional.anthropic.claude-fable-5-1-v1:0", 80.025},
		{"anthropic.claude-fable-5-1", "regional.anthropic.claude-fable-5-1-v1:0", 80.025},
		{"global.anthropic.claude-fable-5-1", "global.anthropic.claude-fable-5-1-v1:0", 72.75},
		{"global.anthropic.claude-fable-5-1-v1:0", "global.anthropic.claude-fable-5-1-v1:0", 72.75},
	}
	usage := genai_prices.Usage{
		genai_prices.UsageInputTokens:      3_000_000,
		genai_prices.UsageCacheReadTokens:  1_000_000,
		genai_prices.UsageCacheWriteTokens: 1_000_000,
		genai_prices.UsageOutputTokens:     1_000_000,
	}
	for _, test := range tests {
		t.Run(test.model, func(t *testing.T) {
			calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
				Usage: usage, Model: test.model, ProviderID: "aws",
			})
			if err != nil {
				t.Fatal(err)
			}
			if calculation.ModelID != test.modelID {
				t.Fatalf("got model %q, want %q", calculation.ModelID, test.modelID)
			}
			if math.Abs(calculation.TotalPrice-test.wantTotal) > 1e-9 {
				t.Fatalf("got total %g, want %g", calculation.TotalPrice, test.wantTotal)
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

// Opus 5.5 caches reads at 0.05x of a $4 base input; Opus 5 at 0.1x of $5. The Opus 5 records
// matched by prefix, so `claude-opus-5-5` silently resolved to Opus 5 and was priced 2.5x too
// high on cache reads instead of failing.
func TestClaudeOpus55DoesNotUseOpus5Prices(t *testing.T) {
	tests := []struct {
		providerID string
		opus5      string
		opus55     string
		wantPrice  float64
	}{
		{"anthropic", "claude-opus-5", "claude-opus-5-5", 0.2},
		{"anthropic", "claude-opus-5-20260901", "claude-opus-5-5-20260922", 0.2},
		{"google", "claude-opus-5", "claude-opus-5-5", 0.2},
		{"google", "claude-opus-5@20260901", "claude-opus-5-5@20260922", 0.2},
		{"google", "publishers/anthropic/models/claude-opus-5", "publishers/anthropic/models/claude-opus-5-5", 0.2},
		{"aws", "global.anthropic.claude-opus-5", "global.anthropic.claude-opus-5-5", 0.2},
		{"aws", "global.anthropic.claude-opus-5-v1:0", "global.anthropic.claude-opus-5-5-v1:0", 0.2},
		{"aws", "us.anthropic.claude-opus-5", "us.anthropic.claude-opus-5-5", 0.22},
		{"aws", "us.anthropic.claude-opus-5-v1:0", "us.anthropic.claude-opus-5-5-v1:0", 0.22},
		{"aws", "eu.anthropic.claude-opus-5", "eu.anthropic.claude-opus-5-5", 0.22},
		{"aws", "au.anthropic.claude-opus-5", "au.anthropic.claude-opus-5-5", 0.22},
		{"aws", "jp.anthropic.claude-opus-5", "jp.anthropic.claude-opus-5-5", 0.22},
		{"aws", "anthropic.claude-opus-5", "anthropic.claude-opus-5-5", 0.22},
		{"openrouter", "anthropic/claude-opus-5", "anthropic/claude-opus-5.5", 0.2},
	}
	usage := genai_prices.Usage{
		genai_prices.UsageInputTokens:     1_000_000,
		genai_prices.UsageCacheReadTokens: 1_000_000,
	}
	for _, test := range tests {
		t.Run(test.providerID+"/"+test.opus55, func(t *testing.T) {
			opus5, err := genai_prices.Calculate(genai_prices.PriceRequest{
				Usage: usage, Model: test.opus5, ProviderID: test.providerID,
			})
			if err != nil {
				t.Fatal(err)
			}
			opus55, err := genai_prices.Calculate(genai_prices.PriceRequest{
				Usage: usage, Model: test.opus55, ProviderID: test.providerID,
			})
			if err != nil {
				t.Fatal(err)
			}
			if opus5.ModelID == opus55.ModelID {
				t.Fatalf("Opus 5.5 resolved to the Opus 5 record %q", opus55.ModelID)
			}
			if math.Abs(opus55.TotalPrice-test.wantPrice) > 1e-9 {
				t.Fatalf("got cache-read price %g, want %g", opus55.TotalPrice, test.wantPrice)
			}
			if math.Abs(opus55.TotalPrice*2.5-opus5.TotalPrice) > 1e-9 {
				t.Fatalf("got %g for Opus 5.5 and %g for Opus 5, want a 2.5x split", opus55.TotalPrice, opus5.TotalPrice)
			}
		})
	}
}

// The Opus 5 clauses were tightened to stop at Opus 5; its dated and `-v1:0` forms must still resolve.
func TestTightenedClaudeOpus5MatchersKeepExistingForms(t *testing.T) {
	for _, test := range []struct{ providerID, model, wantModelID string }{
		{"anthropic", "claude-opus-5-20260901", "claude-opus-5"},
		{"google", "claude-opus-5@20260901", "claude-opus-5"},
		{"aws", "global.anthropic.claude-opus-5-v1:0", "global.anthropic.claude-opus-5"},
		{"aws", "us.anthropic.claude-opus-5-v1:0", "regional.anthropic.claude-opus-5"},
	} {
		calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000}, Model: test.model, ProviderID: test.providerID,
		})
		if err != nil {
			t.Fatal(err)
		}
		if calculation.ModelID != test.wantModelID {
			t.Fatalf("%s/%s resolved to %q, want %q", test.providerID, test.model, calculation.ModelID, test.wantModelID)
		}
	}
}

// OpenRouter's family-level alias moved to Opus 5.5 on release; earlier requests keep the Opus 5 rate.
func TestOpenRouterClaudeOpusLatestMovesToOpus55(t *testing.T) {
	tests := []struct {
		timestamp time.Time
		want      float64
	}{
		{time.Date(2026, 9, 21, 23, 59, 0, 0, time.UTC), 25.5},
		{time.Date(2026, 9, 22, 0, 0, 0, 0, time.UTC), 20.2},
	}
	for _, test := range tests {
		calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Usage: genai_prices.Usage{
				genai_prices.UsageInputTokens:     1_000_000,
				genai_prices.UsageCacheReadTokens: 1_000_000,
				genai_prices.UsageOutputTokens:    1_000_000,
			},
			Model:      "~anthropic/claude-opus-latest",
			ProviderID: "openrouter",
			Timestamp:  test.timestamp,
		})
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(calculation.TotalPrice-test.want) > 1e-9 {
			t.Fatalf("at %s got %g, want %g", test.timestamp, calculation.TotalPrice, test.want)
		}
	}
}

// Sonnet 5.5 shares Sonnet 5's rates, so only the resolved model shows the Sonnet 5 prefix matchers no longer claim it.
func TestClaudeSonnet55ResolvesToItsOwnModel(t *testing.T) {
	for _, test := range []struct {
		providerID, model, wantModelID string
		wantPrice                      float64
	}{
		{"anthropic", "claude-sonnet-5-5", "claude-sonnet-5-5", 12},
		{"anthropic", "claude-sonnet-5-5-20260928", "claude-sonnet-5-5", 12},
		{"google", "claude-sonnet-5-5", "claude-sonnet-5-5", 12},
		{"google", "claude-sonnet-5-5@20260928", "claude-sonnet-5-5", 12},
		{"google", "publishers/anthropic/models/claude-sonnet-5-5", "claude-sonnet-5-5", 12},
		{"aws", "global.anthropic.claude-sonnet-5-5", "global.anthropic.claude-sonnet-5-5", 12},
		{"aws", "global.anthropic.claude-sonnet-5-5-v1:0", "global.anthropic.claude-sonnet-5-5", 12},
		{"aws", "us.anthropic.claude-sonnet-5-5", "regional.anthropic.claude-sonnet-5-5", 13.2},
		{"aws", "us.anthropic.claude-sonnet-5-5-v1:0", "regional.anthropic.claude-sonnet-5-5", 13.2},
		{"aws", "anthropic.claude-sonnet-5-5", "regional.anthropic.claude-sonnet-5-5", 13.2},
		{"openrouter", "anthropic/claude-sonnet-5.5", "anthropic/claude-sonnet-5.5", 12},
	} {
		calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Usage: genai_prices.Usage{
				genai_prices.UsageInputTokens:  1_000_000,
				genai_prices.UsageOutputTokens: 1_000_000,
			},
			Model:      test.model,
			ProviderID: test.providerID,
		})
		if err != nil {
			t.Fatal(err)
		}
		if calculation.ModelID != test.wantModelID {
			t.Fatalf("%s/%s resolved to %q, want %q", test.providerID, test.model, calculation.ModelID, test.wantModelID)
		}
		if math.Abs(calculation.TotalPrice-test.wantPrice) > 1e-9 {
			t.Fatalf("%s/%s got %g, want %g", test.providerID, test.model, calculation.TotalPrice, test.wantPrice)
		}
	}
}

// The Sonnet 5 clauses were tightened to stop at Sonnet 5; its dated and `-v1:0` forms must still resolve.
func TestTightenedClaudeSonnet5MatchersKeepExistingForms(t *testing.T) {
	for _, test := range []struct{ providerID, model, wantModelID string }{
		{"anthropic", "claude-sonnet-5", "claude-sonnet-5"},
		{"anthropic", "claude-sonnet-5-20260630", "claude-sonnet-5"},
		{"google", "claude-sonnet-5@20260630", "claude-sonnet-5"},
		{"aws", "global.anthropic.claude-sonnet-5", "global.anthropic.claude-sonnet-5-v1:0"},
		{"aws", "global.anthropic.claude-sonnet-5-v1:0", "global.anthropic.claude-sonnet-5-v1:0"},
		{"aws", "us.anthropic.claude-sonnet-5-v1:0", "regional.anthropic.claude-sonnet-5-v1:0"},
		{"aws", "anthropic.claude-sonnet-5", "regional.anthropic.claude-sonnet-5-v1:0"},
	} {
		calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000}, Model: test.model, ProviderID: test.providerID,
		})
		if err != nil {
			t.Fatal(err)
		}
		if calculation.ModelID != test.wantModelID {
			t.Fatalf("%s/%s resolved to %q, want %q", test.providerID, test.model, calculation.ModelID, test.wantModelID)
		}
	}
}

// OpenRouter's family-level Sonnet alias resolves to $2/$10 Sonnet 5.5 from the date that was verified.
func TestOpenRouterClaudeSonnetLatestMovesToSonnet55(t *testing.T) {
	tests := []struct {
		timestamp time.Time
		want      float64
	}{
		{time.Date(2026, 9, 27, 23, 59, 0, 0, time.UTC), 18},
		{time.Date(2026, 9, 28, 0, 0, 0, 0, time.UTC), 12},
	}
	for _, test := range tests {
		calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Usage: genai_prices.Usage{
				genai_prices.UsageInputTokens:  1_000_000,
				genai_prices.UsageOutputTokens: 1_000_000,
			},
			Model:      "~anthropic/claude-sonnet-latest",
			ProviderID: "openrouter",
			Timestamp:  test.timestamp,
		})
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(calculation.TotalPrice-test.want) > 1e-9 {
			t.Fatalf("at %s got %g, want %g", test.timestamp, calculation.TotalPrice, test.want)
		}
	}
}

func TestDatabricksPrices(t *testing.T) {
	for _, test := range []struct {
		model, wantModelID string
		wantPrice          float64
	}{
		{"databricks-kimi-k3", "databricks-kimi-k3", 18.3},
		{"databricks-deepseek-v4-flash-0731", "databricks-deepseek-v4-flash-0731", 0.448},
		{"databricks-deepseek-v4-pro-0813", "databricks-deepseek-v4-pro-0813", 5.412},
		{"system.ai.glm-5-3", "databricks-glm-5-3", 6.06},
		{"databricks-qwen35-122b-a10b", "databricks-qwen35-122b-a10b", 2.64},
		{"databricks-gpt-oss-120b", "databricks-gpt-oss-120b", 0.9},
	} {
		calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Usage: genai_prices.Usage{
				genai_prices.UsageInputTokens:     2_000_000,
				genai_prices.UsageCacheReadTokens: 1_000_000,
				genai_prices.UsageOutputTokens:    1_000_000,
			},
			Model:      test.model,
			ProviderID: "databricks",
		})
		if err != nil {
			t.Fatal(err)
		}
		if calculation.ModelID != test.wantModelID || math.Abs(calculation.TotalPrice-test.wantPrice) > 1e-9 {
			t.Fatalf("%s resolved to %q at %g, want %q at %g", test.model, calculation.ModelID, calculation.TotalPrice, test.wantModelID, test.wantPrice)
		}
	}
}

func TestDatabricksProviderSelection(t *testing.T) {
	for _, request := range []genai_prices.PriceRequest{
		{Model: "databricks-gpt-oss-120b", ProviderAPIURL: "https://my-workspace.cloud.databricks.com/serving-endpoints/chat/completions"},
		{Model: "databricks-gpt-oss-120b", ProviderAPIURL: "https://adb-1234567890123456.7.azuredatabricks.net/serving-endpoints/databricks-gpt-oss-120b/invocations"},
		{Model: "databricks-gpt-oss-120b", ProviderAPIURL: "https://1234567890123456.7.gcp.databricks.com/ai-gateway/mlflow/v1/chat/completions"},
		{Model: "databricks-gpt-oss-120b"},
		{Model: "system.ai.gpt-oss-120b"},
		{Model: "databricks/databricks-gpt-oss-120b", ProviderID: "litellm"},
	} {
		request.Usage = genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000}
		calculation, err := genai_prices.Calculate(request)
		if err != nil {
			t.Fatal(err)
		}
		if calculation.ProviderID != "databricks" || calculation.ModelID != "databricks-gpt-oss-120b" || math.Abs(calculation.TotalPrice-0.15) > 1e-9 {
			t.Fatalf("%#v resolved to %#v", request, calculation)
		}
	}

	upstream, err := genai_prices.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1}, Model: "kimi-k3",
	})
	if err != nil {
		t.Fatal(err)
	}
	if upstream.ProviderID != "moonshotai" {
		t.Fatalf("kimi-k3 resolved to provider %q, want moonshotai", upstream.ProviderID)
	}

	for _, providerAPIURL := range []string{
		"https://my-workspace.cloud.databricks.com.evil.test/serving-endpoints/chat/completions",
		"https://adb-1234567890123456.7.azuredatabricks.net.evil.test/serving-endpoints/databricks-gpt-oss-120b/invocations",
		"https://1234567890123456.7.gcp.databricks.com.evil.test/ai-gateway/mlflow/v1/chat/completions",
		"https://my-workspace.cloud.databricks.com/api/2.0/clusters/list",
	} {
		_, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1}, Model: "databricks-gpt-oss-120b", ProviderAPIURL: providerAPIURL,
		})
		if !errors.Is(err, genai_prices.ErrProviderNotFound) {
			t.Fatalf("%s: got %v, want ErrProviderNotFound", providerAPIURL, err)
		}
	}
}

// The Databricks bodies follow the documented usage fields; no recorded response is public.
// https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/api-reference#usage
func TestDatabricksExtractUsage(t *testing.T) {
	chatBody := `{"object":"chat.completion","model":"databricks-glm-5-3","usage":{"prompt_tokens":12011,"completion_tokens":80,` +
		`"total_tokens":12091,"reasoning_tokens":30,"cache_read_input_tokens":12002}}`
	chatUsage := genai_prices.Usage{
		genai_prices.UsageInputTokens:           12_011,
		genai_prices.UsageCacheReadTokens:       12_002,
		genai_prices.UsageOutputTokens:          80,
		genai_prices.UsageOutputReasoningTokens: 30,
	}
	for _, test := range []struct {
		request   genai_prices.ExtractRequest
		wantModel string
		wantUsage genai_prices.Usage
		wantPrice float64
	}{
		{
			request:   genai_prices.ExtractRequest{ResponseJSON: []byte(chatBody), ProviderID: "databricks"},
			wantModel: "databricks-glm-5-3", wantUsage: chatUsage, wantPrice: 0.00348512,
		},
		{
			request:   genai_prices.ExtractRequest{ResponseJSON: []byte(chatBody), ProviderID: "databricks", APIFlavor: "chat"},
			wantModel: "databricks-glm-5-3", wantUsage: chatUsage, wantPrice: 0.00348512,
		},
		{
			request: genai_prices.ExtractRequest{
				ResponseJSON: []byte(`{"object":"chat.completion","model":"databricks-gpt-oss-120b",` +
					`"usage":{"prompt_tokens":7,"completion_tokens":74,"total_tokens":81}}`),
				ProviderID: "databricks",
				APIFlavor:  "chat",
			},
			wantModel: "databricks-gpt-oss-120b",
			wantUsage: genai_prices.Usage{genai_prices.UsageInputTokens: 7, genai_prices.UsageOutputTokens: 74},
			wantPrice: 0.00004545,
		},
		{
			request: genai_prices.ExtractRequest{
				ResponseJSON: []byte(`{"object":"response","model":"databricks-kimi-k3","usage":{"input_tokens":100,` +
					`"input_tokens_details":{"cached_tokens":40},"output_tokens":50,"output_tokens_details":{"reasoning_tokens":20},"total_tokens":150}}`),
				ProviderAPIURL: "https://adb-1234567890123456.7.azuredatabricks.net/serving-endpoints/open-responses",
				APIFlavor:      "responses",
			},
			wantModel: "databricks-kimi-k3",
			wantUsage: genai_prices.Usage{
				genai_prices.UsageInputTokens:           100,
				genai_prices.UsageCacheReadTokens:       40,
				genai_prices.UsageOutputTokens:          50,
				genai_prices.UsageOutputReasoningTokens: 20,
			},
			wantPrice: 0.000942,
		},
		{
			request: genai_prices.ExtractRequest{
				ResponseJSON: []byte(`{"object":"list","model":"databricks-gte-large-en","data":[{"object":"embedding","index":0,` +
					`"embedding":[0.1,0.2]}],"usage":{"prompt_tokens":1000000,"total_tokens":1000000}}`),
				ProviderID: "databricks",
				APIFlavor:  "embeddings",
			},
			wantModel: "databricks-gte-large-en",
			wantUsage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000},
			wantPrice: 0.13,
		},
	} {
		extracted, err := genai_prices.ExtractUsage(test.request)
		if err != nil {
			t.Fatal(err)
		}
		if extracted.ProviderID != "databricks" || extracted.Model != test.wantModel || !maps.Equal(extracted.Usage, test.wantUsage) {
			t.Fatalf("%s: got %#v", test.request.APIFlavor, extracted)
		}
		calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Usage: extracted.Usage, Model: extracted.Model, ProviderID: extracted.ProviderID,
		})
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(calculation.TotalPrice-test.wantPrice) > 1e-12 {
			t.Fatalf("%s: got %g, want %g", test.request.APIFlavor, calculation.TotalPrice, test.wantPrice)
		}
	}
}

// 0.75M five-minute and 0.25M one-hour cache writes. The regional endpoint carries a 10% premium.
func TestAWSConverseCacheWriteTTL(t *testing.T) {
	wantUsage := genai_prices.Usage{
		genai_prices.UsageInputTokens:        1_000_000,
		genai_prices.UsageCacheReadTokens:    0,
		genai_prices.UsageCacheWriteTokens:   1_000_000,
		genai_prices.UsageCacheWrite5MTokens: 750_000,
		genai_prices.UsageCacheWrite1HTokens: 250_000,
		genai_prices.UsageOutputTokens:       0,
	}
	for _, test := range []struct {
		model     string
		wantPrice float64
	}{
		{"global.anthropic.claude-sonnet-4-6", 4.3125},
		{"us.anthropic.claude-sonnet-4-6", 4.74375},
	} {
		body := `{"model":"` + test.model + `","usage":{"inputTokens":0,"cacheReadInputTokens":0,"cacheWriteInputTokens":1000000,` +
			`"cacheDetails":[{"ttl":"1h","inputTokens":250000},{"ttl":"5m","inputTokens":750000}],"outputTokens":0,"totalTokens":1000000}}`
		extracted, err := genai_prices.ExtractUsage(genai_prices.ExtractRequest{ResponseJSON: []byte(body), ProviderID: "aws"})
		if err != nil {
			t.Fatal(err)
		}
		if extracted.ProviderID != "aws" || extracted.Model != test.model || !maps.Equal(extracted.Usage, wantUsage) {
			t.Fatalf("%s: got %#v", test.model, extracted)
		}
		calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Usage: extracted.Usage, Model: extracted.Model, ProviderID: extracted.ProviderID,
		})
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(calculation.TotalPrice-test.wantPrice) > 1e-12 {
			t.Fatalf("%s: got %g, want %g", test.model, calculation.TotalPrice, test.wantPrice)
		}
	}
}

// Haiku 5.5 bills every token at 5x once the prompt exceeds 100,000 tokens; exactly 100,000 stays on the base rate
// and 100,001 does not.
func TestClaudeHaiku55PricesByPromptLength(t *testing.T) {
	for _, test := range []struct {
		providerID, model, wantModelID string
		wantBase, wantLongContext      float64
	}{
		{"anthropic", "claude-haiku-5-5", "claude-haiku-5-5", 0.06, 0.3000005},
		{"anthropic", "claude-haiku-5-5-20261007", "claude-haiku-5-5", 0.06, 0.3000005},
		{"google", "claude-haiku-5-5", "claude-haiku-5-5", 0.06, 0.3000005},
		{"google", "claude-haiku-5-5@20261007", "claude-haiku-5-5", 0.06, 0.3000005},
		{"google", "publishers/anthropic/models/claude-haiku-5-5", "claude-haiku-5-5", 0.06, 0.3000005},
		{"aws", "global.anthropic.claude-haiku-5-5", "global.anthropic.claude-haiku-5-5", 0.06, 0.3000005},
		{"aws", "global.anthropic.claude-haiku-5-5-v1:0", "global.anthropic.claude-haiku-5-5", 0.06, 0.3000005},
		{"aws", "us.anthropic.claude-haiku-5-5", "regional.anthropic.claude-haiku-5-5", 0.066, 0.33000055},
		{"aws", "eu.anthropic.claude-haiku-5-5-v1:0", "regional.anthropic.claude-haiku-5-5", 0.066, 0.33000055},
		{"aws", "anthropic.claude-haiku-5-5", "regional.anthropic.claude-haiku-5-5", 0.066, 0.33000055},
		{"openrouter", "anthropic/claude-haiku-5.5", "anthropic/claude-haiku-5.5", 0.06, 0.3000005},
		{"openrouter", "anthropic/claude-haiku-5.5-20261007", "anthropic/claude-haiku-5.5", 0.06, 0.3000005},
		{"openrouter", "anthropic/claude-haiku-5.5:batch", "anthropic/claude-haiku-5.5:batch", 0.03, 0.15000025},
	} {
		for _, tokens := range []struct {
			usage genai_prices.Usage
			want  float64
		}{
			{genai_prices.Usage{genai_prices.UsageInputTokens: 100_000, genai_prices.UsageOutputTokens: 100_000}, test.wantBase},
			{genai_prices.Usage{genai_prices.UsageInputTokens: 100_001, genai_prices.UsageOutputTokens: 100_000}, test.wantLongContext},
		} {
			calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
				Usage:      tokens.usage,
				Model:      test.model,
				ProviderID: test.providerID,
			})
			if err != nil {
				t.Fatal(err)
			}
			if calculation.ModelID != test.wantModelID {
				t.Fatalf("%s/%s resolved to %q, want %q", test.providerID, test.model, calculation.ModelID, test.wantModelID)
			}
			if math.Abs(calculation.TotalPrice-tokens.want) > 1e-9 {
				t.Fatalf("%s/%s with %v got %g, want %g", test.providerID, test.model, tokens.usage, calculation.TotalPrice, tokens.want)
			}
		}
	}
}

func TestOpenRouterClaudeHaiku55OneHourCacheWrites(t *testing.T) {
	for _, test := range []struct {
		model                     string
		wantBase, wantLongContext float64
	}{
		{"anthropic/claude-haiku-5.5", 0.02, 0.100001},
		{"anthropic/claude-haiku-5.5-20261007", 0.02, 0.100001},
		{"anthropic/claude-haiku-5.5:batch", 0.01, 0.0500005},
		{"~anthropic/claude-haiku-latest", 0.02, 0.100001},
	} {
		for _, sample := range []struct {
			tokens float64
			want   float64
		}{{100_000, test.wantBase}, {100_001, test.wantLongContext}} {
			calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
				Usage: genai_prices.Usage{
					genai_prices.UsageInputTokens:        sample.tokens,
					genai_prices.UsageCacheWriteTokens:   sample.tokens,
					genai_prices.UsageCacheWrite1HTokens: sample.tokens,
				},
				Model:      test.model,
				ProviderID: "openrouter",
				Timestamp:  time.Date(2026, 10, 7, 0, 0, 0, 0, time.UTC),
			})
			if err != nil {
				t.Fatal(err)
			}
			if math.Abs(calculation.TotalPrice-sample.want) > 1e-12 {
				t.Fatalf("%s with %g tokens got %g, want %g", test.model, sample.tokens, calculation.TotalPrice, sample.want)
			}
		}
	}
}

// OpenRouter's family-level Haiku alias moved from $1/$5 Haiku 4.5 to tiered Haiku 5.5 on its release.
func TestOpenRouterClaudeHaikuLatestMovesToHaiku55(t *testing.T) {
	for _, test := range []struct {
		timestamp time.Time
		want      float64
	}{
		{time.Date(2026, 10, 6, 23, 59, 0, 0, time.UTC), 6},
		{time.Date(2026, 10, 7, 0, 0, 0, 0, time.UTC), 3},
	} {
		calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Usage: genai_prices.Usage{
				genai_prices.UsageInputTokens:  1_000_000,
				genai_prices.UsageOutputTokens: 1_000_000,
			},
			Model:      "~anthropic/claude-haiku-latest",
			ProviderID: "openrouter",
			Timestamp:  test.timestamp,
		})
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(calculation.TotalPrice-test.want) > 1e-9 {
			t.Fatalf("at %s got %g, want %g", test.timestamp, calculation.TotalPrice, test.want)
		}
	}
}
