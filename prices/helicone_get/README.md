This directory is responsible for fetching prices from Helicone and exporting them to JSON format.

We can't use python as we do for OpenRouter and LiteLLM since the data is stored in typescript files.

Ultimately this code is responsible for just writing `../source_prices/helicone.json` which is used for
detecting price discrepancies.

## Keep `--allow-write` scoped

`main.ts` **imports** `cost/providers/mappings.ts`, which is Helicone's TypeScript copied in by
`pull.sh`. Importing it means upstream code runs during this task. None of the other five price
importers do that — they parse inert JSON.

`deno.json` therefore scopes `--allow-write` to `../source_prices`, the one directory `main.ts` writes.
Deno denies net, read, run and env by default, so with write scoped as well, this task can only touch
the file it is meant to produce. That keeps an unexpected upstream change contained to the same
gitignored output every other price source writes, where review already catches it.

**Please don't widen this to a bare `--allow-write`** — the narrow form costs nothing, since `main.ts`
only ever writes the one path.
