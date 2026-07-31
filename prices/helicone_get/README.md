This directory is responsible for fetching prices from Helicone and exporting them to JSON format.

We can't use python as we do for OpenRouter and LiteLLM since the data is stored in typescript files.

Ultimately this code is responsible for just writing `../source_prices/helicone.json` which is used for
detecting price discrepancies.

## This importer runs third-party code — keep both guards in place

`main.ts` **imports** `cost/providers/mappings.ts`, which is Helicone's TypeScript copied in by
`pull.sh`. Importing it executes its module-level code on whatever machine runs `make helicone-get`.
None of the other five price importers do this — they parse inert JSON. Two things keep that safe:

1. **`deno.json` scopes `--allow-write` to `../source_prices`.** Unscoped, a compromised upstream
   could write any file the invoking user can, and arbitrary write becomes code execution via a shell
   rc file or a git hook. Deno denies net, run, read and env by default and none are granted here, so
   with write scoped the worst case is bad numbers in a gitignored JSON file — the same trust level as
   every other price source, and already gated by review. Do not widen this to a bare `--allow-write`.
2. **`pull.sh` pins `HELICONE_SHA`.** Tracking `main` meant every run executed whatever had landed
   upstream since the last one, unreviewed.

### Bumping the pin

```bash
# pick the new commit
gh api repos/Helicone/helicone/commits/main --jq .sha

# edit HELICONE_SHA in pull.sh, then
make helicone-get
```

Confirm the resulting diff in `../source_prices/helicone.json` is only price data, and commit the SHA
bump on its own so it is reviewable.
