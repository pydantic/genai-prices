package genai_prices_test

import (
	"errors"
	"math"
	"testing"
	"time"

	"github.com/pydantic/genai-prices/packages/go"
)

func TestGemini38TTSRates(t *testing.T) {
	for _, test := range []struct {
		model   string
		context map[string]string
		totals  [2]float64
	}{
		{"gemini-3.8-flash-tts", nil, [2]float64{9.5, 19}},
		{"gemini-3.8-flash-tts", map[string]string{"processing": "batch"}, [2]float64{4.75, 9.5}},
		{"gemini-3.8-flash-tts", map[string]string{"service_tier": "flex"}, [2]float64{4.75, 9.5}},
		{"gemini-3.8-flash-tts", map[string]string{"service_tier": "priority"}, [2]float64{17.1, 34.2}},
		{"gemini-3.8-flash-lite-tts", nil, [2]float64{6.5, 13}},
		{"gemini-3.8-flash-lite-tts", map[string]string{"processing": "batch"}, [2]float64{3.25, 6.5}},
		{"gemini-3.8-flash-lite-tts", map[string]string{"service_tier": "flex"}, [2]float64{3.25, 6.5}},
		{"gemini-3.8-flash-lite-tts", map[string]string{"service_tier": "priority"}, [2]float64{11.7, 23.4}},
	} {
		for period, timestamp := range []time.Time{
			time.Date(2026, 12, 31, 23, 59, 0, 0, time.UTC),
			time.Date(2027, 1, 1, 0, 0, 0, 0, time.UTC),
		} {
			price, err := genai_prices.Calculate(genai_prices.PriceRequest{
				Usage: genai_prices.Usage{
					genai_prices.UsageInputTokens:       1_000_000,
					genai_prices.UsageOutputTokens:      1_000_000,
					genai_prices.UsageOutputAudioTokens: 1_000_000,
				},
				Model: test.model, ProviderID: "google", Timestamp: timestamp, PriceContext: test.context,
			})
			if err != nil {
				t.Fatal(err)
			}
			if price.ModelID != test.model || math.Abs(price.TotalPrice-test.totals[period]) > 1e-9 {
				t.Fatalf("%s %v at %s: got %+v, want %g", test.model, test.context, timestamp, price, test.totals[period])
			}
		}
	}
}

func TestVerifiedPriceCheckAdditions(t *testing.T) {
	tokenUsage := genai_prices.Usage{
		genai_prices.UsageInputTokens:     1_000_000,
		genai_prices.UsageCacheReadTokens: 250_000,
		genai_prices.UsageOutputTokens:    1_000_000,
	}
	for _, test := range []struct {
		provider string
		model    string
		usage    genai_prices.Usage
		total    float64
	}{
		{"google", "gemini-nano-banana-2.1", genai_prices.Usage{genai_prices.UsageWebSearches: 1_000}, 14},
		{"moonshotai", "kimi-k2.6", tokenUsage, 4.7525},
		{"moonshotai", "kimi-k2.7-code", tokenUsage, 4.76},
		{"moonshotai", "kimi-k2.7-code-highspeed", tokenUsage, 9.52},
		{"x-ai", "grok-4.20-multi-agent", genai_prices.Usage{genai_prices.UsageInputTokens: 200_000, genai_prices.UsageOutputTokens: 1_000_000}, 6.4},
	} {
		price, err := genai_prices.Calculate(genai_prices.PriceRequest{Usage: test.usage, Model: test.model, ProviderID: test.provider})
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(price.TotalPrice-test.total) > 1e-9 {
			t.Fatalf("%s got %g, want %g", test.model, price.TotalPrice, test.total)
		}
	}
	_, err := genai_prices.Calculate(genai_prices.PriceRequest{Model: "grok-4.20-multi-agent-0309", ProviderID: "x-ai"})
	if !errors.Is(err, genai_prices.ErrModelNotFound) {
		t.Fatalf("unverified alias: got %v, want ErrModelNotFound", err)
	}
	for _, model := range []string{"jev-1.14.0", "jev-preview"} {
		price, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Model: model, ProviderID: "typesafe", Usage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000_000},
			Timestamp: time.Date(2026, 10, 18, 0, 0, 0, 0, time.UTC),
		})
		if err != nil {
			t.Fatal(err)
		}
		if price.ModelID != "jev-1.14.0" || price.TotalPrice != 0.042 {
			t.Fatalf("%s: unexpected price or model: %+v", model, price)
		}
	}
}
