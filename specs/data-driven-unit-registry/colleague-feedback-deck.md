---
marp: true
theme: default
paginate: true
size: 16:9
---

<style>
section {
  font-size: 22px;
}
table {
  font-size: 18px;
}
blockquote {
  font-size: 22px;
}
pre {
  font-size: 15px;
}
header {
  font-size: 14px;
  color: #999;
}
header strong {
  color: #2563eb;
}
section.title-slide {
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
}
section.part-context,
section.part-proposal,
section.part-feedback,
section.title-slide {
  --h1-color: #fff;
  --heading-strong-color: #fff;
  --fgColor-default: rgba(255, 255, 255, 0.95);
  --fgColor-muted: rgba(255, 255, 255, 0.7);
  color: white;
}
section.part-context {
  background: linear-gradient(135deg, #1e3a5f 0%, #2d5a8e 100%);
}
section.part-proposal {
  background: linear-gradient(135deg, #064e3b 0%, #047857 100%);
}
section.part-feedback {
  background: linear-gradient(135deg, #7a4a1a 0%, #a66b2e 100%);
}
</style>

# What the current hardcoded shape looks like

```python
class AbstractUsage(Protocol):
    @property
    def input_tokens(self) -> int | None: ...
    @property
    def cache_write_tokens(self) -> int | None: ...
    @property
    def cache_read_tokens(self) -> int | None: ...
    @property
    def output_tokens(self) -> int | None: ...
    @property
    def input_audio_tokens(self) -> int | None: ...
    @property
    def cache_audio_read_tokens(self) -> int | None: ...
    @property
    def output_audio_tokens(self) -> int | None: ...

# Implementation of AbstractUsage
@dataclass
class Usage:
    input_tokens: int | None = None
    cache_write_tokens: int | None = None
    cache_read_tokens: int | None = None
    ...

# Used by extractors
UsageField = Literal[
    'input_tokens',
    'cache_write_tokens',
    'cache_read_tokens',
    'output_tokens',
    'input_audio_tokens',
    'cache_audio_read_tokens',
    'output_audio_tokens',
]

@dataclass
class ModelPrice:
    input_mtok: Decimal | TieredPrices | None = None
    cache_write_mtok: Decimal | TieredPrices | None = None
    cache_read_mtok: Decimal | TieredPrices | None = None
    output_mtok: Decimal | TieredPrices | None = None
    input_audio_mtok: Decimal | TieredPrices | None = None
    cache_audio_read_mtok: Decimal | TieredPrices | None = None
    output_audio_mtok: Decimal | TieredPrices | None = None
    requests_kcount: Decimal | None = None
```

---

# Problem

- Many kinds of tokens missing, e.g. image tokens
- Other kinds of usage missing, e.g. tool calls
- `AbstractUsage` is a `Protocol` so we can't simply add fields to it without breaking type checking
- Field names appear in several places, in both Python and JS and any future languages
- Each time a new field is added it would break auto-updates via `data.json`

---

# Unit registry proposal: a new source of truth

```yaml
families:
  tokens:
    per: 1_000_000
    dimensions:
      direction: [input, output]
      modality: [text, audio, image, video]
      cache: [read, write]
    units:
      input_mtok: # catch-all input token unit
        usage_key: input_tokens
        dimensions: { direction: input }
      cache_read_mtok: # (no modality specified)
        usage_key: cache_read_tokens
        dimensions: { direction: input, cache: read }
      input_audio_mtok: # (no caching specified)
        usage_key: input_audio_tokens
        dimensions: { direction: input, modality: audio }
      cache_audio_read_mtok: # combination of both
        usage_key: cache_audio_read_tokens
        dimensions: { direction: input, modality: audio, cache: read }
      # And so on for:
      # - Cache write tokens
      # - Output tokens
      # - Other modalities: image, video, text

  requests:
    per: 1_000
    dimensions: {}
    units:
      requests_kcount: {}
```

---

# Unit families other than tokens:

- Builtin tool calls (e.g., web search, file search)
- Images
- Duration-based billing (e.g., audio/video seconds)
- Character counts (alternative to tokens)

---

# The source of truth moves up a level

| Today                                            | Direction                                          |
| ------------------------------------------------ | -------------------------------------------------- |
| `Usage` fields define what usage exists          | Registry defines units and usage keys              |
| `ModelPrice` fields define what prices exist     | Registry defines unit IDs                          |
| Extractor `dest` is tied to a fixed literal type | Extractor `dest` is validated against the registry |
| Schemas mirror hardcoded fields                  | Schemas are derived from the registry              |

---

# Why this has taken longer than expected

- This is not just a refactor inside pricing math
- It introduces a new meta-schema that feeds multiple layers of the system
- The abstraction only really pays off if several pieces move together
- That makes it harder to carve into very small, isolated changes

---

# The change cuts across the whole pipeline

- provider YAML prices
- extractor destinations
- `Usage`
- `ModelPrice`
- validation rules
- generated schemas
- runtime-updated `data.json`
- compatibility shims for the existing API

> This feels less like adding a feature and more like changing where the system's truth lives

---

# What I want feedback on

- **Is the unit-registry abstraction the right one**
- **Is the problem important enough to justify this level of system change**
- **Does this feel like a solid long-term direction or like over-generalization**
- **Is there a narrower approach that gets most of the value with less cross-cutting change**
