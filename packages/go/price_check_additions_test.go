package genai_prices_test

import (
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
		{"x-ai", "grok-4.20-multi-agent", genai_prices.Usage{genai_prices.UsageInputTokens: 200_000, genai_prices.UsageOutputTokens: 1_000_000}, 5.5},
		{"x-ai", "grok-4.20-multi-agent-0309", genai_prices.Usage{genai_prices.UsageInputTokens: 200_000, genai_prices.UsageOutputTokens: 1_000_000}, 5.5},
	} {
		price, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Usage: test.usage, Model: test.model, ProviderID: test.provider, Timestamp: time.Date(2026, 10, 17, 0, 0, 0, 0, time.UTC),
		})
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(price.TotalPrice-test.total) > 1e-9 {
			t.Fatalf("%s got %g, want %g", test.model, price.TotalPrice, test.total)
		}
	}
	batch, err := genai_prices.Calculate(genai_prices.PriceRequest{
		Usage:        genai_prices.Usage{genai_prices.UsageInputTokens: 200_000, genai_prices.UsageOutputTokens: 1_000_000},
		Model:        "grok-4.20-multi-agent-0309",
		ProviderID:   "x-ai",
		Timestamp:    time.Date(2026, 10, 17, 0, 0, 0, 0, time.UTC),
		PriceContext: map[string]string{"processing": "batch"},
	})
	if err != nil || math.Abs(batch.TotalPrice-4.4) > 1e-9 {
		t.Fatalf("grok-4.20-multi-agent-0309 batch: got %+v, %v, want 4.4", batch, err)
	}
	for _, alias := range []string{"grok-4.20-multi-agent", "grok-4.20-multi-agent-beta-0309", "grok-4.20-multi-agent-latest"} {
		price, err := genai_prices.Calculate(genai_prices.PriceRequest{Model: alias, ProviderID: "x-ai"})
		if err != nil || price.ModelID != "grok-4.20-multi-agent-0309" {
			t.Fatalf("%s: got %+v, %v", alias, price, err)
		}
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

func TestTypeSafeJevServedIDs(t *testing.T) {
	var extracted genai_prices.ExtractedUsage
	for _, flavor := range []string{"systemone", ""} {
		var err error
		extracted, err = genai_prices.ExtractUsage(genai_prices.ExtractRequest{
			ProviderID:   "openrouter",
			APIFlavor:    flavor,
			ResponseJSON: []byte(`{"model":"typesafe/jev-1.14-20261014","answers":{"is_bug":{"type":"noul","noul":0.96}},"usage":{"cost":0.5,"input_tokens":285,"output_tokens":23}}`),
		})
		if err != nil {
			t.Fatal(err)
		}
		if extracted.Model != "typesafe/jev-1.14-20261014" || extracted.Usage[genai_prices.UsageInputTokens] != 285 ||
			extracted.Usage[genai_prices.UsageOutputTokens] != 23 {
			t.Fatalf("%q: unexpected extracted usage: %#v", flavor, extracted)
		}
	}
	for providerID, modelID := range map[string]string{"openrouter": "typesafe/jev-1.14", "typesafe": "jev-1.14.0"} {
		price, err := genai_prices.Calculate(genai_prices.PriceRequest{
			Model: extracted.Model, ProviderID: providerID, Usage: extracted.Usage,
		})
		if err != nil {
			t.Fatal(err)
		}
		if price.ModelID != modelID || math.Abs(price.TotalPrice-0.00001197) > 1e-12 {
			t.Fatalf("%s: unexpected price or model: %+v", providerID, price)
		}
		for _, model := range []string{"typesafe/jev-1.140", "typesafe/jev-1.14-2026101", "typesafe/jev-router"} {
			if _, err := genai_prices.Calculate(genai_prices.PriceRequest{Model: model, ProviderID: providerID}); err == nil {
				t.Fatalf("%s: %s matched a Jev version", providerID, model)
			}
		}
	}
}

func TestGrok420PriceCut(t *testing.T) {
	for _, model := range []string{"grok-4.20", "grok-4.20-multi-agent"} {
		for day, total := range map[int]float64{29: 12.8, 30: 5.5} {
			price, err := genai_prices.Calculate(genai_prices.PriceRequest{
				Usage: genai_prices.Usage{genai_prices.UsageInputTokens: 200_000, genai_prices.UsageOutputTokens: 1_000_000},
				Model: model, ProviderID: "x-ai", Timestamp: time.Date(2026, 4, day, 0, 0, 0, 0, time.UTC),
			})
			if err != nil || math.Abs(price.TotalPrice-total) > 1e-9 {
				t.Fatalf("%s on 2026-04-%d: got %+v, %v, want %g", model, day, price, err, total)
			}
		}
	}
}
