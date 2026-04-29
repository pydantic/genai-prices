# Decomposition Algorithm

This document explains the decomposition model used by the spec examples. The
prose spec is the source of truth. The full-depth formula below relies on the
registry and price-coverage rules in the prose spec: registry interval closure,
registry join-closedness, price ancestor coverage, and price join coverage.
Those rules reject sparse shapes that would make this formula silently wrong.

## Mobius Inversion on the Containment Poset

The containment poset is defined by dimension set inclusion: unit A is an
ancestor of unit B if A's dimensions are a subset of B's. Only priced units
become cost buckets; unpriced reported usage keys are ignored unless they are
needed to infer a missing priced value.

Descendant/ancestor relationships are determined by the full registry poset (dimension set inclusion), not just the priced subset. Only priced units participate in the sum, but the depth of each unit is its total number of dimensions regardless of what else is priced.

For each priced unit U, the leaf value (exclusive token count) is:

```
leaf(U) = sum over all priced descendants V of U (including U itself):
            (-1)^(depth(V) - depth(U)) * usage(V)
```

where `depth(V)` = number of dimension assignments on V (e.g., unit `input_tokens` has 1: `{direction: input}`, unit `cache_audio_read_tokens` has 3: `{direction: input, modality: audio, cache: read}`), and `usage(V)` = the usage value looked up by V's usage key. In the tokens family, the least-specific units have one dimension (direction) — there is no zero-dimension root unit. Families with no dimensions (e.g., `requests`) have a single unit and no decomposition to perform.

This is standard Mobius inversion on a product of chains (our dimensions are independent categorical axes).

## Sparse Registry Guardrails

The full-depth sign rule assumes there are no structural gaps that affect the
priced set. It works for the built-in symmetric token registry and for other
closed shapes where registry closure and price coverage give the formula the
intermediate units and prices it relies on.

It is wrong when a registry allows a specific unit without structurally
important intermediate units. For example, if a family has `input_tokens`,
`cache_read_tokens`, and `cache_video_read_tokens`, but no
`input_video_tokens`, the full-depth formula would add `cache_video_read_tokens`
back into the `input_tokens` catch-all. That may be commercially wrong: cached
video can be a special price while intermediate categories fall through to the
broader input price.

The main spec resolves this with registry interval closure plus registry
join-closedness. The example registry is invalid unless it also defines
`input_video_tokens`. If `cache_read_tokens` is also an intermediate ancestor of
`cache_video_read_tokens`, ancestor coverage requires its price when cached
video is priced. If those intermediate categories use the same commercial rate
as ordinary input tokens, the model repeats the numeric price explicitly. That
duplication is intentional; it keeps the registry and price data structurally
complete and lets the full-depth formula remain the general runtime rule.

## Usage Value Reads

Usage is not normalized at construction time and there is no eager
decomposition pre-pass. `calc_price` wraps raw usage in the registry-aware usage
representation and asks for only the values it needs:

- If a requested value was reported, it is returned directly without checking
  other reported fields for contradictions.
- If no relevant data exists, the value is zero.
- If a missing value is determined by reported descendants, it is inferred for
  that read.
- If a missing value is underdetermined or depends on contradictory reported
  values, the read raises a user-facing usage error.

Inferred usage values are not cached. Re-reading a missing value recomputes it
from the stored reported values and the active registry.

Example: usage is `{input_audio_tokens: 300}`, priced units are `input_tokens` (price key `input_mtok`) and `input_audio_tokens` (price key `input_audio_mtok`).

- `input_audio_tokens` is a leaf: usage = 300 (provided).
- `input_tokens` is not provided. Reading it can infer 300 from the descendant.
- `leaf(input_tokens) = 300 - 300 = 0`. `leaf(input_audio_tokens) = 300`.
- Total: 300 tokens priced, all at the audio rate.

If `input_tokens` were explicitly provided as 1000: `leaf(input_tokens) = 1000 - 300 = 700`. No inference needed — both values are known.

## Two-way example

Priced: `input_tokens` (1 dimension, price key `input_mtok`), `cache_read_tokens` (2 dimensions, price key `cache_read_mtok`).

```
leaf(input_tokens)      = usage(input_tokens) - usage(cache_read_tokens)
leaf(cache_read_tokens) = usage(cache_read_tokens)
```

## Three-way overlap

Priced: `input_tokens` (1 dim), `cache_read_tokens` (2 dims), `input_audio_tokens` (2 dims), `cache_audio_read_tokens` (3 dims). Their price keys are `input_mtok`, `cache_read_mtok`, `input_audio_mtok`, and `cache_audio_read_mtok`.

```
leaf(input_tokens)            = input_tokens - cache_read_tokens - input_audio_tokens + cache_audio_read_tokens
leaf(cache_read_tokens)       = cache_read_tokens - cache_audio_read_tokens
leaf(input_audio_tokens)      = input_audio_tokens - cache_audio_read_tokens
leaf(cache_audio_read_tokens) = cache_audio_read_tokens
```

The `+cache_audio_read_tokens` in `leaf(input_tokens)` is the inclusion-exclusion correction: without it, tokens that are both cached and audio would be subtracted twice.

## Why this works

The containment poset is a product of flat lattices — one per dimension axis. Each axis contributes a flat lattice: "unspecified" at the bottom, with the axis's values (e.g., `text`, `audio`, `image`, `video` for modality) incomparable above it. The product of these lattices gives the full poset. The Mobius function for a product of flat lattices is `mu(U, V) = (-1)^(depth(V) - depth(U))` when V is a descendant of U (i.e., U's dimensions are a subset of V's), and 0 otherwise. Each step from U toward V adds exactly one dimension assignment, and the signs alternate. This is a standard result in combinatorics — the product formula for Mobius functions.

The key property: the sum of all leaf values equals the root usage value. Every token is in exactly one leaf bucket.

## Negative leaf values

If `leaf(U) < 0`, the priced usage values cannot be reconciled — a
more-specific count does not fit inside a less-specific count after overlap
correction. Price calculation raises a user-facing error instead of reporting a
negative or nonsensical cost.

This check is demand-driven. Contradictory reported usage is allowed to exist,
and direct reads of stored values still return the stored values. `calc_price`
raises only when the contradiction affects priced buckets or a value it must
infer. For example, `{input_tokens: 100, cache_read_tokens: 200}` is acceptable
for a model that only prices `input_tokens`; the cache value is unpriced and not
needed. The same usage must fail for a model that also prices
`cache_read_tokens`, because the priced buckets cannot be reconciled.
