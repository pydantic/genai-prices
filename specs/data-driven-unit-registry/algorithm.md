# Decomposition Algorithm

This document explains the decomposition model used by the spec examples. The
prose spec is the source of truth. The algorithm below relies on the registry
and price-coverage rules in the prose spec: registry interval closure, registry
join-closedness, price ancestor coverage, and price join coverage. Those rules
reject sparse shapes that would make exclusive buckets ambiguous.

## Exclusive Subtraction on the Containment Poset

The containment poset is defined by full dimension set inclusion: unit A is an
ancestor of unit B if A's dimensions are a subset of B's. The required `family`
dimension participates in that same comparison; units from different family
dimension values are incompatible because their `family` values conflict. Only
priced units become cost buckets; unpriced reported usage keys are ignored
unless they are needed to detect that a priced ancestor or overlap was omitted.

Descendant/ancestor relationships are determined by the full registry poset
(dimension set inclusion), not just the priced subset. Only priced units
participate in the subtraction.

Process priced units from most specific to least specific. For each priced unit
U, the leaf value (exclusive token count) is:

```
leaf(U) = usage(U) - sum over all strict priced descendants V of U: leaf(V)
```

where `usage(V)` is the usage value looked up by V's usage key. Subtracting
already-exclusive descendants works for ordinary orthogonal dimensions and for
conditional dimensions whose valid containment poset is not a full Cartesian
product. The current `requests` unit is an explicit one-request-per-`Usage`-
object pricing rule, not caller-reported usage that needs decomposition.

## Sparse Registry Guardrails

The general subtraction rule can calculate a sparse priced poset, but the
registry still may not omit structurally important units. For example, if a
family dimension value has `input_tokens`, `cache_read_tokens`, and
`cache_video_read_tokens`, but no `input_video_tokens`, custom pricing could not
independently price ordinary video and cached video even though those concepts
are compatible.

The main spec resolves this with registry interval closure plus registry
join-closedness. The example registry is invalid unless it also defines
`input_video_tokens`. If `cache_read_tokens` is also an intermediate ancestor of
`cache_video_read_tokens`, ancestor coverage requires its price when cached
video is priced. If those intermediate categories use the same commercial rate
as ordinary input tokens, the model repeats the numeric price explicitly. That
duplication is intentional; it keeps the registry and price data structurally
complete.

The complete registry handles this by requiring the structurally important
intermediate units and by rejecting priced sets that lack required joins before
decomposition runs. Conditional dimension requirements exclude combinations
that are structurally invalid rather than weakening these checks.

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
leaf(cache_read_tokens) = usage(cache_read_tokens)
leaf(input_tokens)      = usage(input_tokens) - leaf(cache_read_tokens)
```

## Three-way overlap

Priced: `input_tokens` (2 dims), `cache_read_tokens` (3 dims), `input_audio_tokens` (3 dims), `cache_audio_read_tokens` (4 dims). Their price keys are `input_mtok`, `cache_read_mtok`, `input_audio_mtok`, and `cache_audio_read_mtok`.

```
leaf(cache_audio_read_tokens) = cache_audio_read_tokens
leaf(cache_read_tokens)       = cache_read_tokens - leaf(cache_audio_read_tokens)
leaf(input_audio_tokens)      = input_audio_tokens - leaf(cache_audio_read_tokens)
leaf(input_tokens)            = input_tokens - leaf(cache_read_tokens) - leaf(input_audio_tokens) - leaf(cache_audio_read_tokens)
```

Because the join bucket is made exclusive first, subtracting every descendant
leaf from `input_tokens` performs the same inclusion-exclusion correction
without relying on dimension-count parity.

## Why this works

Every more-specific priced count is converted to an exclusive bucket before an
ancestor is processed. Subtracting all strict descendant buckets therefore
removes each classified usage value exactly once. Under each least-specific
unit, the sum of its descendant leaf values equals that unit's usage value, so
every token in that subtree lands in exactly one bucket. This property depends
on required joins being priced: without an explicit overlap bucket, two
incomparable descendants could still describe the same usage.

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
