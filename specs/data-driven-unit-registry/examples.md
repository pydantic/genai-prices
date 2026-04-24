# Pricing Examples

These examples use approximate prices to show how the unit system handles real pricing patterns. YAML `prices` entries use price keys such as `input_mtok`; decomposition labels use usage-keyed units such as `input_tokens`.

## Audio Model — OpenAI GPT-4o Realtime

```yaml
- id: gpt-4o-realtime-preview
  prices:
    input_mtok: 5
    output_mtok: 20
    cache_read_mtok: 2.5
    input_audio_mtok: 100
    output_audio_mtok: 200
    cache_audio_read_mtok: 2.5
```

Audio tokens are much more expensive than text. The catch-all unit `input_tokens` is priced by `input_mtok`, which is the text price. Decomposition: `input_tokens` leaf = input_tokens - cache_read_tokens - input_audio_tokens + cache_audio_read_tokens.

## Image Generation — OpenAI gpt-image-1.5

```yaml
- id: gpt-image-1-5
  prices:
    input_mtok: 5
    input_image_mtok: 8
    output_mtok: 32
    output_image_mtok: 32
```

Catch-all convention: unit `input_tokens` priced by `input_mtok` is text since there's no `input_text_mtok`. Unit `output_tokens` priced by `output_mtok` and unit `output_image_tokens` priced by `output_image_mtok` are the same price because image is the default output modality. If someone sends only `{input_tokens: 1000, output_tokens: 500}` with no breakdown, all output tokens land in the `output_tokens` catch-all at $32/M — the image-rate catch-all. The `output_image_tokens` leaf is 0 (no `output_image_tokens` reported).

## Multimodal Input — Google Gemini 2.5 Pro

```yaml
- id: gemini-2.5-pro
  prices:
    input_mtok: 1.25
    output_mtok: 10
    cache_read_mtok: 0.13
    input_audio_mtok: 0.30
    cache_audio_read_mtok: 0.03
    input_video_mtok: 0.30
    cache_video_read_mtok: 0.03
    input_image_mtok: 0.30
    cache_image_read_mtok: 0.03
```

Separate rates per modality. The catch-all unit `input_tokens` priced by `input_mtok` ($1.25) is the text rate; other modalities are cheaper. Cached variants defined for each. This model also has long-context tiers handled by the existing `TieredPrices` mechanism.

## Image-Primary — Catch-All Convention

```yaml
- id: hypothetical-image-model
  prices:
    input_mtok: 5
    input_image_mtok: 5
    input_text_mtok: 2
    output_mtok: 20
    output_image_mtok: 20
    output_text_mtok: 10
```

Image is the default modality. Someone sending `input_tokens: 1000` with no breakdown pays the image rate ($5). Someone sending `input_tokens: 1000` and `input_text_tokens: 300` gets 300 at text ($2) and 700 at image ($5).

## Transcription — OpenAI

```yaml
- id: gpt-4o-transcribe
  prices:
    input_mtok: 2.5
    input_audio_mtok: 2.5
    output_mtok: 10
```

Audio in (audio tokens), text out (output tokens). Unit `input_tokens` (`input_mtok`) and unit `input_audio_tokens` (`input_audio_mtok`) are the same price — this model only takes audio input, but the catch-all ancestor is required.

## Simple Decomposition Walkthrough

A model prices two input units in a parent-child chain (no sibling overlap, so join coverage is not triggered):

- `input_tokens` via `input_mtok` at $3/M (catch-all input)
- `cache_read_tokens` via `cache_read_mtok` at $0.30/M (cached input)
- `output_tokens` via `output_mtok` at $15/M

Usage: `{input_tokens: 1000, cache_read_tokens: 200, output_tokens: 500}`

Leaf values:

- `cache_read_tokens`: 200 (no more-specific priced unit)
- `input_tokens`: 1000 - 200 = 800 (remainder)
- `output_tokens`: 500

Cost: `(800/1M) x 3 + (200/1M) x 0.30 + (500/1M) x 15 = $0.01006`

## Decomposition With Overlap (Join Coverage)

A model prices four input units — including the join required by join coverage:

- `input_tokens` via `input_mtok` at $5/M (catch-all input)
- `cache_read_tokens` via `cache_read_mtok` at $0.50/M (cached input)
- `input_audio_tokens` via `input_audio_mtok` at $100/M (audio input)
- `cache_audio_read_tokens` via `cache_audio_read_mtok` at $2.50/M (cached audio input — the join of cache_read and input_audio)
- `output_tokens` via `output_mtok` at $20/M

Usage: `{input_tokens: 1000, cache_read_tokens: 200, input_audio_tokens: 300, cache_audio_read_tokens: 50, output_tokens: 500}`

Leaf values (inclusion-exclusion via Mobius inversion):

- `cache_audio_read_tokens`: 50 (leaf — no descendants)
- `cache_read_tokens`: 200 - 50 = 150 (subtract cached-audio)
- `input_audio_tokens`: 300 - 50 = 250 (subtract cached-audio)
- `input_tokens`: 1000 - 200 - 300 + 50 = 550 (the +50 corrects for double-subtraction)
- `output_tokens`: 500

Sum: 50 + 150 + 250 + 550 + 500 = 1500 = 1000 + 500. Every token in exactly one bucket.

See [algorithm](algorithm.md) for the general formula.
