# Pricing Examples

These examples use approximate prices to show how the unit system handles real pricing patterns.

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

Audio tokens are much more expensive than text. The catch-all `input_mtok` is the text price. Decomposition: `input_mtok` leaf = input_tokens - cache_read_tokens - input_audio_tokens + cache_audio_read_tokens.

## Image Generation — OpenAI gpt-image-1.5

```yaml
- id: gpt-image-1-5
  prices:
    input_mtok: 5
    input_image_mtok: 8
    output_mtok: 32
    output_image_mtok: 32
```

Catch-all convention: `input_mtok` is text since there's no `input_text_mtok`. `output_mtok` and `output_image_mtok` are the same price (image is the default output modality). If someone sends only `{input_tokens: 1000, output_tokens: 500}` with no breakdown, they pay text input ($5) and image output ($32).

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

Separate rates per modality. The catch-all `input_mtok` ($1.25) is the text rate; other modalities are cheaper. Cached variants defined for each. This model also has long-context tiers handled by the existing `TieredPrices` mechanism.

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

Audio in (audio tokens), text out (output tokens). `input_mtok` and `input_audio_mtok` are the same price — this model only takes audio input, but the catch-all ancestor is required.

## Decomposition Walkthrough

A model prices three token units:

- `input_mtok` at $3/M (catch-all input)
- `cache_read_mtok` at $0.30/M (cached input)
- `input_audio_mtok` at $100/M (audio input)

Usage: `{input_tokens: 1000, cache_read_tokens: 200, input_audio_tokens: 300}`

Leaf values (each unit gets only its exclusive portion):

- `input_audio_mtok`: 300 (no more-specific priced unit)
- `cache_read_mtok`: 200 (no more-specific priced unit)
- `input_mtok`: 1000 - 200 - 300 = 500 (remainder)

Cost: `(500/1M) x 3 + (200/1M) x 0.30 + (300/1M) x 100 = $0.03156`

If the model also priced `cache_audio_read_mtok` at $0.10/M, it would be carved out of both `cache_read_mtok` and `input_audio_mtok`. The engine uses dimension relationships to determine which units overlap and applies inclusion-exclusion (Mobius inversion) to avoid double-counting.
