package genai_prices_test

import (
	"math"
	"testing"
	"time"

	"github.com/pydantic/genai-prices/packages/go"
)

func TestPriceCheckPreservesRatesWithoutAnEffectiveDate(t *testing.T) {
	for _, test := range []struct {
		providerID, model    string
		input, cache, output float64
	}{
		{"avian", "deepseek/deepseek-v4-flash", 0.0805, 0.0165, 0.161},
		{"avian", "deepseek/deepseek-v4-pro-0813", 0.594, 0.0198, 1.782},
		{"avian", "xiaomi/mimo-v2.5-pro", 0.435, 0.0036, 0.87},
		{"avian", "xiaomi/mimo-v2.6-flash", 0.2, 0.05, 0.4},
		{"avian", "xiaomi/mimo-v2.6-pro", 0.435, 0.0036, 0.87},
		{"github-copilot", "claude-sonnet-5.5", 2, 0.20, 10},
	} {
		t.Run(test.providerID+"/"+test.model, func(t *testing.T) {
			for _, timestamp := range []time.Time{
				time.Date(2026, 9, 30, 0, 0, 0, 0, time.UTC),
				time.Date(2026, 10, 9, 0, 0, 0, 0, time.UTC),
			} {
				result, err := genai_prices.Calculate(genai_prices.PriceRequest{
					Usage: genai_prices.Usage{
						genai_prices.UsageInputTokens:     2_000_000,
						genai_prices.UsageCacheReadTokens: 1_000_000,
						genai_prices.UsageOutputTokens:    1_000_000,
					},
					Model:      test.model,
					ProviderID: test.providerID,
					Timestamp:  timestamp,
				})
				if err != nil {
					t.Fatal(err)
				}
				if math.Abs(result.InputPrice-(test.input+test.cache)) > 1e-12 {
					t.Fatalf("at %s input got %g, want %g", timestamp, result.InputPrice, test.input+test.cache)
				}
				if result.OutputPrice != test.output {
					t.Fatalf("at %s output got %g, want %g", timestamp, result.OutputPrice, test.output)
				}
			}
		})
	}
}
