# Decomposition Algorithm

## Mobius Inversion on the Containment Poset

The containment poset is defined by dimension set inclusion: unit A is an ancestor of unit B if A's dimensions are a subset of B's. Only priced units participate — unpriced units are invisible to the algorithm.

Descendant/ancestor relationships are determined by the full registry poset (dimension set inclusion), not just the priced subset. Only priced units participate in the sum, but the depth of each unit is its total number of dimensions regardless of what else is priced.

For each priced unit U, the leaf value (exclusive token count) is:

```
leaf(U) = sum over all priced descendants V of U (including U itself):
            (-1)^(depth(V) - depth(U)) * usage(V)
```

where `depth(V)` = number of dimension assignments on V (e.g., `input_mtok` has 1: `{direction: input}`, `cache_audio_read_mtok` has 3: `{direction: input, modality: audio, cache: read}`), and `usage(V)` = the usage value looked up by V's usage_key. In the tokens family, the least-specific units have one dimension (direction) — there is no zero-dimension root unit. Families with no dimensions (e.g., `requests`) have a single unit and no decomposition to perform.

This is standard Mobius inversion on a product of chains (our dimensions are independent categorical axes).

## Inference of missing ancestor usage

Before applying the Mobius formula, missing usage values are resolved:

1. **Leaf-level priced units** (no more-specific priced descendants): missing usage defaults to 0.
2. **Non-leaf priced units**: missing usage is inferred such that the unit's leaf value is 0 — meaning no remainder beyond what its descendants account for.

Concretely, if `usage(U)` is missing for a non-leaf unit U, it is set to the inclusion-exclusion sum of its priced descendants' usage values. This is the inverse of the Mobius formula with `leaf(U) = 0`.

Example: usage is `{input_audio_tokens: 300}`, priced units are `input_mtok` and `input_audio_mtok`.

- `input_audio_mtok` is a leaf: usage = 300 (provided).
- `input_mtok` is not a leaf: `input_tokens` is missing. Inferred as 300 (sum of descendants).
- `leaf(input_mtok) = 300 - 300 = 0`. `leaf(input_audio_mtok) = 300`.
- Total: 300 tokens priced, all at the audio rate.

If `input_tokens` were explicitly provided as 1000: `leaf(input_mtok) = 1000 - 300 = 700`. No inference needed — both values are known.

## Two-way example

Priced: `input_mtok` (1 dimension), `cache_read_mtok` (2 dimensions).

```
leaf(input_mtok)      = usage(input_tokens) - usage(cache_read_tokens)
leaf(cache_read_mtok)  = usage(cache_read_tokens)
```

## Three-way overlap

Priced: `input_mtok` (1 dim), `cache_read_mtok` (2 dims), `input_audio_mtok` (2 dims), `cache_audio_read_mtok` (3 dims).

```
leaf(input_mtok)            = input_tokens - cache_read_tokens - input_audio_tokens + cache_audio_read_tokens
leaf(cache_read_mtok)       = cache_read_tokens - cache_audio_read_tokens
leaf(input_audio_mtok)      = input_audio_tokens - cache_audio_read_tokens
leaf(cache_audio_read_mtok) = cache_audio_read_tokens
```

The `+cache_audio_read_tokens` in `leaf(input_mtok)` is the inclusion-exclusion correction: without it, tokens that are both cached and audio would be subtracted twice.

## Why this works

The containment poset is a product of flat lattices — one per dimension axis. Each axis contributes a flat lattice: "unspecified" at the bottom, with the axis's values (e.g., `text`, `audio`, `image`, `video` for modality) incomparable above it. The product of these lattices gives the full poset. The Mobius function for a product of flat lattices is `mu(U, V) = (-1)^(depth(V) - depth(U))` when V is a descendant of U (i.e., U's dimensions are a subset of V's), and 0 otherwise. Each step from U toward V adds exactly one dimension assignment, and the signs alternate. This is a standard result in combinatorics — the product formula for Mobius functions.

The key property: the sum of all leaf values equals the root usage value. Every token is in exactly one leaf bucket.

## Negative leaf values

If `leaf(U) < 0`, the explicitly provided usage data is contradictory — a subset's count exceeds its superset's. The algorithm detects this and raises an error with the specific units and values involved. Negative leaves can only arise when both a parent and child usage value are explicitly provided and the child exceeds the parent. Missing ancestor usage is inferred from descendants (the ancestor's leaf value defaults to zero), so incomplete usage never produces negative leaves.
