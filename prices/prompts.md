# Optimising `openai.yml`

I used the following prompt to improve `data/providers/openai.yml`, not doing the rest right now as it was slightly over zealous, and I had to review each change manually.

> there's a bunch of models in this file that can be combined because the `id` are meaningfully equivalent (e.g. `o4-mini` and `o4-mini-2025-04-16`) and the prices are identical. Please combine these into on item and change the `matches` key to be and `or` with all matches from the previous items, like `ada`
