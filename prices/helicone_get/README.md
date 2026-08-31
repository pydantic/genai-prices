This directory is responsible for fetching prices from Helicone and exporting them to JSON format.

We can't use python as we do for OpenRouter and LiteLLM since the data is stored in typescript files.

Ultimately this code is responsible for just writing `../source_prices/helicone.json` which is used for
detecting price discrepancies.

`main.ts` imports `cost/providers/mappings.ts`, which is Helicone's own TypeScript copied in by `pull.sh`, so
upstream code runs during `make helicone-get`. The `run` task in `deno.json` therefore grants only
`--allow-write=../source_prices` (the one path it writes); Deno denies net, read, run and env by default.
Keep it that narrow.
