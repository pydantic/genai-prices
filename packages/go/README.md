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
