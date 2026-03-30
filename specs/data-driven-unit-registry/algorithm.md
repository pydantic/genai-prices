# Decomposition Algorithm

## Mobius Inversion on the Containment Poset

The containment poset is defined by dimension set inclusion: unit A is an ancestor of unit B if A's dimensions are a subset of B's. Only priced units participate — unpriced units are invisible to the algorithm.

For each priced unit U, the leaf value (exclusive token count) is:

```
leaf(U) = sum over all priced descendants V of U (including U itself):
            (-1)^(depth(V) - depth(U)) * usage(V)
```

where `depth(V)` = number of dimensions on V, and `usage(V)` = the usage value looked up by V's usage_key.

This is standard Mobius inversion on a product of chains (our dimensions are independent categorical axes).

## Two-way example

Priced: `input_mtok` (depth 1), `cache_read_mtok` (depth 2).

```
leaf(input_mtok)      = usage(input_tokens) - usage(cache_read_tokens)
leaf(cache_read_mtok)  = usage(cache_read_tokens)
```

## Three-way overlap

Priced: `input_mtok` (depth 1), `cache_read_mtok` (depth 2), `input_audio_mtok` (depth 2), `cache_audio_read_mtok` (depth 3).

```
leaf(input_mtok)            = input_tokens - cache_read_tokens - input_audio_tokens + cache_audio_read_tokens
leaf(cache_read_mtok)       = cache_read_tokens - cache_audio_read_tokens
leaf(input_audio_mtok)      = input_audio_tokens - cache_audio_read_tokens
leaf(cache_audio_read_mtok) = cache_audio_read_tokens
```

The `+cache_audio_read_tokens` in `leaf(input_mtok)` is the inclusion-exclusion correction: without it, tokens that are both cached and audio would be subtracted twice.

## Why this works

The dimensions form a product of chains (direction x modality x cache). Each step in the poset adds exactly one dimension. The Mobius function for a product of chains is `mu(U, V) = (-1)^(depth(V) - depth(U))` when V is a descendant of U, and 0 otherwise. This is a standard result in combinatorics.

The key property: the sum of all leaf values equals the root usage value. Every token is in exactly one leaf bucket.

## Negative leaf values

If `leaf(U) < 0`, the usage data is inconsistent — a subset's count exceeds its superset's. The algorithm detects this and raises an error with the specific units and values involved.
