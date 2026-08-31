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

	genaiprices "github.com/pydantic/genai-prices/packages/go"
)

func main() {
	price, err := genaiprices.Calculate(genaiprices.PriceRequest{
		Usage: genaiprices.Usage{
			genaiprices.UsageInputTokens:  1_000,
			genaiprices.UsageOutputTokens: 100,
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

	genaiprices "github.com/pydantic/genai-prices/packages/go"
)

func main() {
	extracted, err := genaiprices.ExtractUsage(genaiprices.ExtractRequest{
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

	price, err := genaiprices.Calculate(genaiprices.PriceRequest{
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

	genaiprices "github.com/pydantic/genai-prices/packages/go"
)

func main() {
	request, err := http.NewRequestWithContext(
		context.Background(),
		http.MethodGet,
		genaiprices.RemoteDataURL,
		nil,
	)
	if err != nil {
		log.Fatal(err)
	}
	response, err := http.DefaultClient.Do(request)
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
	calculator, err := genaiprices.NewCalculatorFromJSON(data)
	if err != nil {
		log.Fatal(err)
	}

	price, err := calculator.Calculate(genaiprices.PriceRequest{
		Usage: genaiprices.Usage{
			genaiprices.UsageInputTokens: 1_000,
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
