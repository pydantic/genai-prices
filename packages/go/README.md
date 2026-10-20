# GenAI Prices for Go

## Installation

```bash
go get github.com/pydantic/genai-prices/packages/go
```

## Calculate a price

```go
package main

import (
	"fmt"
	"log"

	"github.com/pydantic/genai-prices/packages/go"
)

func main() {
	price, err := genai_prices.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{
			genai_prices.UsageInputTokens:  1_000,
			genai_prices.UsageOutputTokens: 100,
		},
		Model:      "gpt-5",
		ProviderID: "openai",
	})
	if err != nil {
		log.Fatal(err)
	}

	fmt.Printf("$%.6f\n", price.TotalPrice)
}
```

`Calculate` uses pricing data embedded at release time. Pass `ProviderID` when you know the provider. This avoids an
ambiguous model name selecting the wrong provider.

## Request pricing context

```go
package main

import (
	"fmt"
	"time"

	"github.com/pydantic/genai-prices/packages/go"
)

func main() {
	price, err := genai_prices.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{
			genai_prices.UsageInputTokens: 1_000_000,
			genai_prices.UsageOutputTokens: 1_000_000,
		},
		Model: "o3",
		ProviderID: "openai",
		Timestamp: time.Date(2026, 10, 12, 0, 0, 0, 0, time.UTC),
		PriceContext: map[string]string{"service_tier": "flex"},
	})
	if err != nil {
		panic(err)
	}
	fmt.Println(price.TotalPrice) // 5
}
```

You pass `PriceContext` explicitly to select request-specific prices.
Use the `service_tier` reported in OpenAI's response. A priority request can be downgraded and report `default`.
`auto` is a request setting and does not identify the rate you were charged. Extraction does not infer a context.
Tier variants are specific to their provider. If model lookup falls back to another provider, you receive the
standard-price estimate; the fallback provider's tier rates are not applied.

OpenAI variants cover `flex`, `priority`, and `fast` where the published rate table supports them.
`default` selects standard prices on these models. Omit the context for ordinary standard pricing.

If a context matches no variant, you receive the standard-price estimate.
This includes unsupported models, unknown tiers, misspelled keys, and dates without verified tier rates.
The bundled tier rates are verified from October 12, 2026; earlier tier history is not modeled.

## Batch API

```go
package main

import (
	"fmt"
	"time"

	"github.com/pydantic/genai-prices/packages/go"
)

func main() {
	price, err := genai_prices.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{
			genai_prices.UsageInputTokens: 1_000_000,
			genai_prices.UsageOutputTokens: 1_000_000,
		},
		Model: "o3",
		ProviderID: "openai",
		Timestamp: time.Date(2026, 10, 14, 0, 0, 0, 0, time.UTC),
		PriceContext: map[string]string{"processing": "batch"},
	})
	if err != nil {
		panic(err)
	}
	fmt.Println(price.TotalPrice) // 5
}
```

You pass `{"processing": "batch"}` for usage from a provider's batch API. Most providers do not mark batch results in
the response, so you set it yourself. Batch is a separate key from `service_tier` because it is a way of submitting
requests, not a tier: OpenAI batch results report `service_tier: "default"`.

Batch rates are bundled for Anthropic, OpenAI, Google, Mistral, Groq and xAI, verified from October 14, 2026.
A model the provider does not serve in batch returns the standard-price estimate.

## Perplexity web search

For `perplexity/sonar`, pass the search type used in the Perplexity request:

```go
price, err := genai_prices.Calculate(genai_prices.PriceRequest{
	Usage: genai_prices.Usage{genai_prices.UsageWebSearches: 2},
	Model: "perplexity/sonar",
	ProviderID: "perplexity",
	PriceContext: map[string]string{"search_type": "fast"},
})
if err != nil {
	panic(err)
}
fmt.Println(price.TotalPrice) // 0.002
```

The response reports the search count but not the search type, so extraction cannot select the rate automatically.
Pass `search_type: fast` even when a Perplexity preset selects Fast Search. Omitting the context or passing
`search_type: web` uses the standard estimate of $2.50 per thousand searches. The fast rate is $1 per thousand
for requests dated September 24, 2026 onward. Token charges are calculated separately.
See [Perplexity's web-search documentation](https://docs.perplexity.ai/docs/agent-api/tools/web-search).

## Extract usage from a response

```go
package main

import (
	"fmt"
	"log"

	"github.com/pydantic/genai-prices/packages/go"
)

func main() {
	extracted, err := genai_prices.ExtractUsage(genai_prices.ExtractRequest{
		ResponseJSON: []byte(`{
			"model": "gpt-5",
			"usage": {
				"input_tokens": 1000,
				"output_tokens": 100
			}
		}`),
		ProviderID: "openai",
		APIFlavor:  "responses",
	})
	if err != nil {
		log.Fatal(err)
	}

	price, err := genai_prices.Calculate(genai_prices.PriceRequest{
		Usage:      extracted.Usage,
		Model:      extracted.Model,
		ProviderID: extracted.ProviderID,
	})
	if err != nil {
		log.Fatal(err)
	}

	fmt.Printf("$%.6f\n", price.TotalPrice)
}
```

`APIFlavor` selects the response shape used by a provider. For example, OpenAI exposes `chat` and `responses`
shapes.

## Load current pricing data

```go
package main

import (
	"context"
	"fmt"
	"io"
	"log"
	"net/http"
	"time"

	"github.com/pydantic/genai-prices/packages/go"
)

func main() {
	request, err := http.NewRequestWithContext(
		context.Background(),
		http.MethodGet,
		genai_prices.RemoteDataURL,
		nil,
	)
	if err != nil {
		log.Fatal(err)
	}
	client := &http.Client{Timeout: 30 * time.Second}
	response, err := client.Do(request)
	if err != nil {
		log.Fatal(err)
	}
	defer response.Body.Close()

	if response.StatusCode != http.StatusOK {
		log.Fatalf("download prices: %s", response.Status)
	}
	data, err := io.ReadAll(response.Body)
	if err != nil {
		log.Fatal(err)
	}
	calculator, err := genai_prices.NewCalculatorFromJSON(data)
	if err != nil {
		log.Fatal(err)
	}

	price, err := calculator.Calculate(genai_prices.PriceRequest{
		Usage: genai_prices.Usage{
			genai_prices.UsageInputTokens: 1_000,
		},
		Model:      "gpt-5",
		ProviderID: "openai",
	})
	if err != nil {
		log.Fatal(err)
	}

	fmt.Printf("$%.6f\n", price.TotalPrice)
}
```

`NewCalculatorFromJSON` creates an immutable snapshot. A failed download or invalid payload cannot replace a
calculator that your application is already using.
