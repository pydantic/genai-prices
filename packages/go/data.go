package genaiprices

import _ "embed"

//go:embed internal/data/prices.json
var bundledProviderData []byte
