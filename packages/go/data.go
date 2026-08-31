package genai_prices

import _ "embed"

//go:embed internal/data/prices.json
var bundledProviderData []byte
