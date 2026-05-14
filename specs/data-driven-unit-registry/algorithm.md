# Decomposition Algorithm

This document explains the decomposition model used by the spec examples. The
prose spec is the source of truth. The full-depth formula below relies on the
registry and price-coverage rules in the prose spec: registry interval closure,
registry join-closedness, price ancestor coverage, and price join coverage.
Those rules reject sparse shapes that would make this formula silently wrong.

## Mobius Inversion on the Containment Poset

The containment poset is defined by full dimension set inclusion: unit A is an
ancestor of unit B if A's dimensions are a subset of B's. The required `family`
dimension participates in that same comparison; units from different family
dimension values are incompatible because their `family` values conflict. Only
priced units become cost buckets; unpriced reported usage keys are ignored
unless they are needed to detect that a priced ancestor or overlap was omitted.

Descendant/ancestor relationships are determined by the full registry poset (dimension set inclusion), not just the priced subset. Only priced units participate in the sum, but the depth of each unit is its total number of dimensions regardless of what else is priced.

For each priced unit U, the leaf value (exclusive token count) is:

```
leaf(U) = sum over all priced descendants V of U (including U itself):
            (-1)^(depth(V) - depth(U)) * usage(V)
```

where `depth(V)` = number of dimension assignments on V (e.g., unit `input_tokens` has 2: `{family: tokens, direction: input}`, unit `cache_audio_read_tokens` has 4: `{family: tokens, direction: input, modality: audio, cache: read}`), and `usage(V)` = the usage value looked up by V's usage key. Within one family dimension value, the required `family` assignment is shared by every comparable unit, so it does not change the inclusion-exclusion sign differences from the earlier family-object formulation. In the tokens family dimension value, the least-specific usage units have `family` plus one commercial dimension (`direction`) — there is no family-only token root unit. The current `requests` unit is an explicit one-request-per-`Usage`-object pricing rule, not caller-reported usage that needs decomposition.

This is standard Mobius inversion on a product of flat lattices: each dimension is an independent categorical axis whose values are incomparable.

## Sparse Registry Guardrails

The full-depth sign rule assumes there are no structural gaps that affect the
priced set. It works for the built-in symmetric token registry and for other
closed shapes where registry closure and price coverage give the formula the
intermediate units and prices it relies on.

It is wrong when a registry allows a specific unit without structurally
important intermediate units. For example, if a family dimension value has `input_tokens`,
`cache_read_tokens`, and `cache_video_read_tokens`, but no
`input_video_tokens`, the full-depth formula would add `cache_video_read_tokens`
back into the `input_tokens` catch-all. That is commercially wrong when cached
video has a special price while intermediate categories fall through to the
broader input price.

The main spec resolves this with registry interval closure plus registry
join-closedness. The example registry is invalid unless it also defines
`input_video_tokens`. If `cache_read_tokens` is also an intermediate ancestor of
`cache_video_read_tokens`, ancestor coverage requires its price when cached
video is priced. If those intermediate categories use the same commercial rate
as ordinary input tokens, the model repeats the numeric price explicitly. That
duplication is intentional; it keeps the registry and price data structurally
complete and lets the full-depth formula remain the general runtime rule.

The complete registry handles this by requiring the structurally important
intermediate units and by rejecting priced sets that lack required joins before
decomposition runs.

## Usage Value Reads

Usage is not normalized at construction time and there is no eager
decomposition pre-pass. `calc_price` wraps raw usage in the registry-aware usage
representation and asks for only the explicit values it needs:

- If a requested value was reported, it is returned directly without checking
  other reported fields for contradictions.
- If a requested registered value was not reported and no positive reported
  related values could make it non-zero, the read returns zero without
  materializing that zero as reported usage.
- If a requested registered value was not reported and positive reported related
  values mean answering would require inferring an omitted ancestor or overlap,
  the read raises a user-facing missing-usage error.
- During pricing, decomposition asks for the selected priced usage keys through
  the same usage-read path. It can ignore unpriced usage keys it never needs to
  read, and it raises the usage-read error when a priced key is missing and
  would require an omitted ancestor or omitted overlap.
- After those priced values are read, decomposition raises if explicit reported
  priced values imply an impossible negative exclusive bucket.

This document describes explicit-value decomposition only. For direct reads, a
missing registered value is ambiguous when
either a positive reported strict descendant of the requested unit exists, or
the requested unit is the join of two positive reported compatible units that
are incomparable with each other. A missing descendant of a reported ancestor
still reads as zero; missing more-specific usage can mean "not reported", and
that read-time zero is not stored as reported usage.

## Two-way example

Priced: `input_tokens` (2 dimensions, price key `input_mtok`), `cache_read_tokens` (3 dimensions, price key `cache_read_mtok`).

```
leaf(input_tokens)      = usage(input_tokens) - usage(cache_read_tokens)
leaf(cache_read_tokens) = usage(cache_read_tokens)
```

## Three-way overlap

Priced: `input_tokens` (2 dims), `cache_read_tokens` (3 dims), `input_audio_tokens` (3 dims), `cache_audio_read_tokens` (4 dims). Their price keys are `input_mtok`, `cache_read_mtok`, `input_audio_mtok`, and `cache_audio_read_mtok`.

```
leaf(input_tokens)            = input_tokens - cache_read_tokens - input_audio_tokens + cache_audio_read_tokens
leaf(cache_read_tokens)       = cache_read_tokens - cache_audio_read_tokens
leaf(input_audio_tokens)      = input_audio_tokens - cache_audio_read_tokens
leaf(cache_audio_read_tokens) = cache_audio_read_tokens
```

The `+cache_audio_read_tokens` in `leaf(input_tokens)` is the inclusion-exclusion correction: without it, tokens that are both cached and audio would be subtracted twice.

## Why this works

The containment poset is a product of flat lattices — one per dimension axis. Each axis contributes a flat lattice: "unspecified" at the bottom, with the axis's values (e.g., `text`, `audio`, `image`, `video` for modality) incomparable above it. The product of these lattices gives the full poset. The Mobius function for a product of flat lattices is `mu(U, V) = (-1)^(depth(V) - depth(U))` when V is a descendant of U (i.e., U's dimensions are a subset of V's), and 0 otherwise. Each step from U toward V adds exactly one dimension assignment, and the signs alternate. This is a standard result in combinatorics — the product formula for Mobius functions.

The key property: under each least-specific unit, the sum of its descendant leaf values equals that least-specific unit's usage value. Every token in that subtree is in exactly one leaf bucket.

## Negative leaf values

If `leaf(U) < 0`, the priced usage values cannot be reconciled — a
more-specific count does not fit inside a less-specific count after overlap
correction. Price calculation raises a user-facing error instead of reporting a
negative or nonsensical cost.

This check is demand-driven. Contradictory reported usage is allowed to exist,
and direct reads of stored values still return the stored values. Direct reads
and `calc_price` raise only when the contradiction affects the requested missing
value or priced buckets. For example, `{input_tokens: 100, cache_read_tokens: 200}` is acceptable
for a model that only prices `input_tokens`; the cache value is unpriced and not
needed. The same usage must fail for a model that also prices
`cache_read_tokens`, because the priced buckets cannot be reconciled.
