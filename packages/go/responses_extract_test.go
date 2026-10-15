package genai_prices_test

import (
	"maps"
	"math"
	"testing"

	"github.com/pydantic/genai-prices/packages/go"
)

func TestXAIResponsesUsageAndPrice(t *testing.T) {
	// Model and usage excerpt: https://docs.x.ai/developers/rest-api-reference/inference/responses
	// https://docs.x.ai/cookbook/examples/prompt-caching confirms reasoning is included in output_tokens.
	for _, test := range []struct {
		name      string
		body      string
		wantUsage genai_prices.Usage
		wantInput float64
		wantTotal float64
	}{
		{
			name: "with details",
			body: `{"model":"grok-4.20-0309-reasoning","usage":{"input_tokens":131,` +
				`"input_tokens_details":{"cached_tokens":128},"output_tokens":624,` +
				`"output_tokens_details":{"reasoning_tokens":246},"total_tokens":755}}`,
			wantUsage: genai_prices.Usage{
				genai_prices.UsageInputTokens:           131,
				genai_prices.UsageCacheReadTokens:       128,
				genai_prices.UsageOutputTokens:          624,
				genai_prices.UsageOutputReasoningTokens: 246,
			},
			wantInput: 0.00002935,
			wantTotal: 0.00158935,
		},
		{
			name: "without details",
			body: `{"model":"grok-4.20-0309-reasoning","usage":{"input_tokens":131,` +
				`"output_tokens":624,"total_tokens":755}}`,
			wantUsage: genai_prices.Usage{genai_prices.UsageInputTokens: 131, genai_prices.UsageOutputTokens: 624},
			wantInput: 0.00016375,
			wantTotal: 0.00172375,
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			extracted, err := genai_prices.ExtractUsage(genai_prices.ExtractRequest{
				ResponseJSON: []byte(test.body), ProviderID: "x-ai", APIFlavor: "responses",
			})
			if err != nil {
				t.Fatal(err)
			}
			if extracted.Model != "grok-4.20-0309-reasoning" || !maps.Equal(extracted.Usage, test.wantUsage) {
				t.Fatalf("unexpected extraction: %#v", extracted)
			}
			price, err := genai_prices.Calculate(genai_prices.PriceRequest{
				Usage: extracted.Usage, Model: extracted.Model, ProviderID: extracted.ProviderID,
			})
			if err != nil {
				t.Fatal(err)
			}
			if price.ModelID != "grok-4.20" || math.Abs(price.InputPrice-test.wantInput) > 1e-12 ||
				math.Abs(price.OutputPrice-0.00156) > 1e-12 || math.Abs(price.TotalPrice-test.wantTotal) > 1e-12 {
				t.Fatalf("unexpected price: %#v", price)
			}
		})
	}
}
