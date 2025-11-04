This folder is for testing genai-prices against a dataset of real requests.

Currently the dataset is constructed using test VCR cassettes in the pydantic-ai repo. Running `get_raw_bodies.py` (with this repo living next to pydantic-ai) parses those files, extracts the full response bodies, and saves them to `raw_bodies.json`. This script is separate because it's slow, and `raw_bodies.json` is ignored because it's big.

Running `extract_usages.py` will:

- Read response bodies from `raw_bodies.json` if it exists, falling back to the reduced bodies in `usages.json` otherwise.
- For each body, for all providers and extractors (API flavours) possible, use genai-prices to:
  - Extract usage
  - Calculate prices
  - Extract a reduced body
- Write all this data to `usages.json`.
