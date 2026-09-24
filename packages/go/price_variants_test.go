package genai_prices_test

import (
	"errors"
	"fmt"
	"math"
	"reflect"
	"testing"
	"time"

	"github.com/pydantic/genai-prices/packages/go"
)

const (
	flexVariant = `{"when":{"service_tier":"flex"},"prices":{"input_mtok":1,"output_mtok":4}}`
	fastVariant = `{"when":{"service_tier":["priority","fast"]},"prices":{"input_mtok":4,"output_mtok":16}}`
)

func variantCalculator(t *testing.T, variants string) *genai_prices.Calculator {
	t.Helper()
	return newTestCalculator(t, fmt.Sprintf(`[
		{
			"id":"testing","name":"Testing","api_pattern":"testing",
			"models":[{
				"id":"model","match":{"equals":"model"},
				"prices":{"input_mtok":2,"output_mtok":8,"requests_kcount":1000},
				"price_variants":%s
			}]
		},
		{"id":"reseller","name":"Reseller","api_pattern":"reseller","models":[],"fallback_model_providers":["testing"]}
	]`, variants))
}

func calculateVariant(
	t *testing.T,
	calculator *genai_prices.Calculator,
	priceContext map[string]string,
	timestamp time.Time,
) genai_prices.PriceCalculation {
	t.Helper()
	calculation, err := calculator.Calculate(genai_prices.PriceRequest{
		Usage:        genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000, genai_prices.UsageOutputTokens: 1_000_000},
		Model:        "model",
		ProviderID:   "testing",
		Timestamp:    timestamp,
		PriceContext: priceContext,
	})
	if err != nil {
		t.Fatal(err)
	}
	return calculation
}

func TestPriceVariantOverridesOnlyTheKeysItLists(t *testing.T) {
	calculation := calculateVariant(t, variantCalculator(t, "["+flexVariant+"]"), map[string]string{"service_tier": "flex"}, time.Time{})

	if calculation.TotalPrice != 6 {
		t.Fatalf("expected flex input and output with the standard request fee, got %g", calculation.TotalPrice)
	}
	if calculation.PriceVariant == nil || !reflect.DeepEqual(calculation.PriceVariant.When, map[string]any{"service_tier": "flex"}) {
		t.Fatalf("unexpected reported variant: %#v", calculation.PriceVariant)
	}
}

func TestReportedPriceVariantIsACopy(t *testing.T) {
	calculator := variantCalculator(t, "["+fastVariant+"]")
	priority := map[string]string{"service_tier": "priority"}

	calculation := calculateVariant(t, calculator, priority, time.Time{})
	calculation.PriceVariant.When["service_tier"].([]any)[0] = "changed"

	if again := calculateVariant(t, calculator, priority, time.Time{}); again.TotalPrice != 21 {
		t.Fatalf("changing a result changed the calculator's data: got %g", again.TotalPrice)
	}
}

func TestPriceVariantMatching(t *testing.T) {
	calculator := variantCalculator(t, "["+flexVariant+","+fastVariant+"]")
	for _, test := range []struct {
		name         string
		priceContext map[string]string
		expected     float64
	}{
		{"flex", map[string]string{"service_tier": "flex"}, 6},
		{"list priority", map[string]string{"service_tier": "priority"}, 21},
		{"list fast", map[string]string{"service_tier": "fast"}, 21},
		{"no context", nil, 11},
		{"default", map[string]string{"service_tier": "default"}, 11},
		{"auto", map[string]string{"service_tier": "auto"}, 11},
		{"other parameter", map[string]string{"speed": "flex"}, 11},
	} {
		t.Run(test.name, func(t *testing.T) {
			calculation := calculateVariant(t, calculator, test.priceContext, time.Time{})
			if calculation.TotalPrice != test.expected {
				t.Fatalf("expected %g, got %g", test.expected, calculation.TotalPrice)
			}
			if (calculation.PriceVariant == nil) != (test.expected == 11) {
				t.Fatalf("unexpected reported variant: %#v", calculation.PriceVariant)
			}
		})
	}
}

// The build rejects variants that can match the same request, but newer data may have them: the last active wins.
func TestMatchingPriceVariantsAreResolvedTogether(t *testing.T) {
	calculator := variantCalculator(t, `[`+flexVariant+`,{"when":{"service_tier":["flex","other"]},"prices":{"input_mtok":0.5}}]`)

	if calculation := calculateVariant(t, calculator, map[string]string{"service_tier": "flex"}, time.Time{}); calculation.TotalPrice != 9.5 {
		t.Fatalf("expected the last matching variant, got %g", calculation.TotalPrice)
	}
}

func TestDatedPriceVariantAppliesFromItsFirstStartDate(t *testing.T) {
	calculator := variantCalculator(t, `[
		{"when":{"service_tier":"flex"},"constraint":{"start_date":"2026-01-01"},"prices":{"input_mtok":1,"output_mtok":4}},
		{"when":{"service_tier":"flex"},"constraint":{"start_date":"2026-06-01"},"prices":{"input_mtok":0.5}}
	]`)
	for _, test := range []struct {
		day      string
		expected float64
	}{
		{"2025-12-31", 11},
		{"2026-01-01", 6},
		// the later entry replaces the whole variant, so output falls back to the standard rate
		{"2026-06-01", 9.5},
	} {
		timestamp, _ := time.Parse("2006-01-02", test.day)
		if calculation := calculateVariant(t, calculator, map[string]string{"service_tier": "flex"}, timestamp); calculation.TotalPrice != test.expected {
			t.Fatalf("%s: expected %g, got %g", test.day, test.expected, calculation.TotalPrice)
		}
	}
}

func TestPriceVariantsDoNotApplyToFallbackModels(t *testing.T) {
	calculation, err := variantCalculator(t, "["+flexVariant+"]").Calculate(genai_prices.PriceRequest{
		Usage:        genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000, genai_prices.UsageOutputTokens: 1_000_000},
		Model:        "model",
		ProviderID:   "reseller",
		PriceContext: map[string]string{"service_tier": "flex"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if calculation.TotalPrice != 11 || calculation.PriceVariant != nil {
		t.Fatalf("expected standard prices for a borrowed model, got %#v", calculation)
	}
}

// A newer feed can add `when` parameters or value types; this version must load it and charge standard prices.
func TestPriceVariantWhenShapesFromNewerDataNeverMatch(t *testing.T) {
	for name, when := range map[string]string{
		"unknown parameter": `{"service_tier":"flex","speed":"fast"}`,
		"bool value":        `{"service_tier":true}`,
		"object value":      `{"service_tier":{"any_of":["flex"]}}`,
		"non-string list":   `{"service_tier":[1,null]}`,
		"empty":             `{}`,
		"null":              `null`,
	} {
		t.Run(name, func(t *testing.T) {
			calculator := variantCalculator(t, `[{"when":`+when+`,"prices":{"input_mtok":1}}]`)
			if calculation := calculateVariant(t, calculator, map[string]string{"service_tier": "flex"}, time.Time{}); calculation.TotalPrice != 11 {
				t.Fatalf("expected standard prices, got %g", calculation.TotalPrice)
			}
		})
	}
}

func TestPriceVariantsAreValidated(t *testing.T) {
	for name, variants := range map[string]string{
		// a cached-input price needs an input price, which neither the variant nor the standard prices has
		"merged prices":    `[{"when":{"service_tier":"flex"},"prices":{"cache_read_mtok":1}}]`,
		"constraint":       `[{"when":{"service_tier":"flex"},"constraint":{"start_date":"2026-13-01"},"prices":{"input_mtok":1}}]`,
		"missing prices":   `[{"when":{"service_tier":"flex"}}]`,
		"when not a map":   `[{"when":["flex"],"prices":{"input_mtok":1}}]`,
		"price not number": `[{"when":{"service_tier":"flex"},"prices":{"input_mtok":"1"}}]`,
	} {
		t.Run(name, func(t *testing.T) {
			_, err := genai_prices.NewCalculatorFromJSON([]byte(`[{
				"id":"testing","name":"Testing","api_pattern":"testing",
				"models":[{"id":"model","match":{"equals":"model"},"prices":{"output_mtok":8},"price_variants":` + variants + `}]
			}]`))
			if !errors.Is(err, genai_prices.ErrInvalidData) {
				t.Fatalf("expected invalid data, got %v", err)
			}
		})
	}
}

func TestPriceVariantsAreValidatedOverConditionalPrices(t *testing.T) {
	_, err := genai_prices.NewCalculatorFromJSON([]byte(`[{
		"id":"testing","name":"Testing","api_pattern":"testing",
		"models":[{
			"id":"model","match":{"equals":"model"},
			"prices":[{"prices":{"output_mtok":8}},{"constraint":{"start_date":"2026-01-01"},"prices":{"input_mtok":1,"output_mtok":8}}],
			"price_variants":[{"when":{"service_tier":"flex"},"prices":{"cache_read_mtok":1}}]
		}]
	}]`))
	if !errors.Is(err, genai_prices.ErrInvalidData) {
		t.Fatalf("expected the variant over the first conditional price to be rejected, got %v", err)
	}
}

func TestOpenAIServiceTierPrices(t *testing.T) {
	// below the 272K-token long-context tier OpenAI's models price separately
	usage := genai_prices.Usage{genai_prices.UsageInputTokens: 100_000, genai_prices.UsageOutputTokens: 100_000}
	for _, test := range []struct {
		model        string
		priceContext map[string]string
		timestamp    time.Time
		expected     float64
	}{
		// gpt-5.4 per 1M tokens: $2.50 in / $15 out standard, flex $1.25 / $7.50, fast $5 / $30
		{"gpt-5.4", nil, time.Time{}, 1.75},
		{"gpt-5.4", map[string]string{"service_tier": "flex"}, time.Time{}, 0.875},
		{"gpt-5.4", map[string]string{"service_tier": "priority"}, time.Time{}, 3.5},
		{"gpt-5.4", map[string]string{"service_tier": "fast"}, time.Time{}, 3.5},
		{"gpt-5.4", map[string]string{"service_tier": "default"}, time.Time{}, 1.75},
		// gpt-5.4-nano has no fast rates
		{"gpt-5.4-nano", map[string]string{"service_tier": "priority"}, time.Time{}, 0.145},
		// gpt-5.6-sol's flex rates are only published for its prices from 2026-08-21
		{"gpt-5.6-sol", map[string]string{"service_tier": "flex"}, time.Date(2026, 8, 20, 0, 0, 0, 0, time.UTC), 3.5},
		{"gpt-5.6-sol", map[string]string{"service_tier": "flex"}, time.Date(2026, 8, 21, 0, 0, 0, 0, time.UTC), 1.2},
	} {
		calculation, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Usage:        usage,
			Model:        test.model,
			ProviderID:   "openai",
			Timestamp:    test.timestamp,
			PriceContext: test.priceContext,
		})
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(calculation.TotalPrice-test.expected) > 1e-12 {
			t.Fatalf("%s %v: expected %g, got %g", test.model, test.priceContext, test.expected, calculation.TotalPrice)
		}
	}
}
