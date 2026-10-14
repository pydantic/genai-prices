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
standard-price estimate; the fallback provider's tier rates are not applied. You are warned when those rates would have
changed the price, or when the context has a value the model has no rate for under a key it prices.

OpenAI variants cover `flex`, `priority`, and `fast` where the published rate table supports them.
`default` selects standard prices on these models. Omit the context for ordinary standard pricing.

If a model has variants for a context key but none match, `PriceCalculation.Warnings` records the fallback and you receive the standard-price estimate.
This includes unknown tiers and dates without verified tier rates.
A context whose keys none of the model's variants use cannot change its price, so it is priced at standard rates without a warning.
This covers models with no tier rates and misspelled keys.
The bundled tier rates are verified from October 12, 2026; earlier tier history is not modeled.
Check `Warnings` when you require a verified tier price.

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
A model without batch rates returns the standard-price estimate.

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
