This directory is responsible for fetching prices from Helicone and exporting them to JSON format.

We can't use python as we do for OpenRouter and LiteLLM since the data is stored in typescript files.

Ultimately this code is responsible for just writing `../source_prices/helicone.json` which is used for
detecting price discrepancies.
