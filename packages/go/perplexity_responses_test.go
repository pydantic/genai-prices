package genai_prices_test

import (
	"maps"
	"math"
	"testing"
	"time"

	"github.com/pydantic/genai-prices/packages/go"
)

func TestPerplexityResponsesUsageAndPrice(t *testing.T) {
	// Constructed from the Agent model/schema and Perplexity's synthetic usage test, not a recording:
	// https://docs.perplexity.ai/docs/agent-api/models
	// https://github.com/perplexityai/wandr/blob/9ea23c7f24d0aaabc2c87b26815a513001b2e7ce/agents/relay/tests/test_perplexity_usage.py
	// https://docs.perplexity.ai/docs/agent-api/tools/web-search
	for _, test := range []struct {
		name      string
		body      string
		wantUsage genai_prices.Usage
		wantInput float64
		withTools bool
	}{
		{
			name: "with details",
			body: `{"model":"perplexity/sonar","object":"response","usage":{"input_tokens":1000,` +
				`"input_tokens_details":{"cache_read_input_tokens":800,"cached_tokens":300},"output_tokens":100,` +
				`"output_tokens_details":{"reasoning_tokens":50},"total_tokens":1100,` +
				`"tool_calls_details":{"search_web":{"invocation":2}}}}`,
			wantUsage: genai_prices.Usage{
				genai_prices.UsageInputTokens:           1_000,
				genai_prices.UsageCacheReadTokens:       800,
				genai_prices.UsageOutputTokens:          100,
				genai_prices.UsageOutputReasoningTokens: 50,
				genai_prices.UsageWebSearches:           2,
			},
			wantInput: 0.0001,
			withTools: true,
		},
		{
			name: "without details",
			body: `{"model":"perplexity/sonar","object":"response","usage":{"input_tokens":1000,` +
				`"output_tokens":100,"total_tokens":1100}}`,
			wantUsage: genai_prices.Usage{genai_prices.UsageInputTokens: 1_000, genai_prices.UsageOutputTokens: 100},
			wantInput: 0.00025,
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			extracted, err := genai_prices.ExtractUsage(genai_prices.ExtractRequest{
				ResponseJSON: []byte(test.body), ProviderID: "perplexity", APIFlavor: "responses",
			})
			if err != nil {
				t.Fatal(err)
			}
			if extracted.Model != "perplexity/sonar" || !maps.Equal(extracted.Usage, test.wantUsage) {
				t.Fatalf("unexpected extraction: %#v", extracted)
			}
			for _, context := range []struct {
				month     time.Month
				day       int
				context   map[string]string
				wantTotal float64
			}{
				{time.October, 15, nil, 0.00535},
				{time.October, 15, map[string]string{"search_type": "web"}, 0.00535},
				{time.September, 24, map[string]string{"search_type": "fast"}, 0.00235},
				{time.October, 14, map[string]string{"search_type": "fast"}, 0.00235},
				{time.October, 15, map[string]string{"search_type": "fast"}, 0.00235},
			} {
				price, err := genai_prices.Calculate(genai_prices.PriceRequest{
					Usage: extracted.Usage, Model: extracted.Model, ProviderID: extracted.ProviderID,
					Timestamp: time.Date(2026, context.month, context.day, 0, 0, 0, 0, time.UTC), PriceContext: context.context,
				})
				if err != nil {
					t.Fatal(err)
				}
				wantTotal := context.wantTotal
				if !test.withTools {
					wantTotal = 0.0005
				}
				if price.ModelID != "perplexity/sonar" || math.Abs(price.InputPrice-test.wantInput) > 1e-12 ||
					math.Abs(price.OutputPrice-0.00025) > 1e-12 || math.Abs(price.TotalPrice-wantTotal) > 1e-12 {
					t.Fatalf("unexpected price: %#v", price)
				}
			}
		})
	}
}
