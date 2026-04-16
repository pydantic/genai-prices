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

<!-- _class: lead title-slide -->

# Data-driven unit registry

## High-level sense check

**Audience**: Fellow engineers
**Goal**: Feedback on the direction
**Date**: April 2026

---

# Questions this deck should answer

1. **What problem am I actually trying to solve**
2. **What changes if units become data-driven**
3. **Why has this become a much larger change than expected**
4. **What stays compatible for users of the library**
5. **Should we keep pushing on this approach or solve it differently**

---

<!-- _class: lead title-slide -->

# Agenda

### Part 1: Context

What is hard today and what is new here

### Part 2: Proposal

What the unit registry is and how it changes the source of truth

### Part 3: Feedback

Why this is hard to split up and what I want reactions to

---

<!-- _header: "" -->
<!-- _class: lead part-context -->

# Part 1: Context

**What problem exists already, and what this proposal adds**

---

<!-- header: "**Context** > Proposal > Feedback" -->

# The pricing problem already has real complexity

- We already need to price overlapping buckets correctly
- We already need to handle incomplete usage data
- We already need to preserve familiar APIs like `calc_price(usage)`
- None of that depends on whether units are configurable

> The overlap and inference problems are inherent to accurate pricing, not created by the registry idea

---

# What is new in this proposal

- A **unit registry** becomes a higher-level source of truth
- That source of truth feeds prices, usage, extractors, validation, and schemas
- New units should be added by editing data, not by editing Python and TypeScript types
- The goal is to remove repeated hardcoded assumptions from the system

---

# What the current hardcoded shape looks like

```python
AbstractUsage = object

@dataclass
class Usage:
    input_tokens: int | None = None
    cache_write_tokens: int | None = None
    cache_read_tokens: int | None = None
    output_tokens: int | None = None
    input_audio_tokens: int | None = None
    cache_audio_read_tokens: int | None = None
    output_audio_tokens: int | None = None

UsageField = Literal[
    "input_tokens",
    "cache_write_tokens",
    "cache_read_tokens",
    "output_tokens",
    "input_audio_tokens",
    "cache_audio_read_tokens",
    "output_audio_tokens",
]
```

- Today the set of valid usage fields is still effectively baked into code
- Extractors and pricing logic inherit that same fixed shape

---

<!-- _header: "" -->
<!-- _class: lead part-proposal -->

# Part 2: Proposal

**Make the units explicit in data, then derive the rest from that**

---

<!-- header: "Context > **Proposal** > Feedback" -->

# What the unit registry looks like

```yaml
families:
  tokens:
    per: 1_000_000
    dimensions:
      direction: [input, output]
      modality: [text, audio, image, video]
      cache: [read, write]
    units:
      input_mtok:
        usage_key: input_tokens
        dimensions: { direction: input }
      cache_read_mtok:
        usage_key: cache_read_tokens
        dimensions: { direction: input, cache: read }
      input_audio_mtok:
        usage_key: input_audio_tokens
        dimensions: { direction: input, modality: audio }
      cache_audio_read_mtok:
        usage_key: cache_audio_read_tokens
        dimensions: { direction: input, modality: audio, cache: read }
```

- This is the core abstraction
- It describes the units, their names, and how they relate

---

# The source of truth moves up a level

| Today                                            | Direction                                          |
| ------------------------------------------------ | -------------------------------------------------- |
| `Usage` fields define what usage exists          | Registry defines units and usage keys              |
| `ModelPrice` fields define what prices exist     | Registry defines unit IDs                          |
| Extractor `dest` is tied to a fixed literal type | Extractor `dest` is validated against the registry |
| Schemas mirror hardcoded fields                  | Schemas are derived from the registry              |

> The point is not just configurability - it is replacing duplicated hardcoded knowledge with one shared model

---

# Compatibility goal

```python
price = calc_price(usage, model_ref="gpt-5")
model_price.input_mtok
usage.input_tokens
```

- The public API shape should stay familiar
- Internally the implementation becomes more dynamic
- Externally existing calling patterns should continue to work
- This is also why the design is awkward in places: new abstraction, old API

---

# One practical example of the cross-cutting effect

```python
@dataclass
class UsageExtractorMapping:
    path: ExtractPath
    dest: UsageField
    required: bool = True
```

- Today `dest` is constrained by a hardcoded `UsageField` literal
- With a registry, `dest` should become any registry-backed usage key
- That change ripples into provider YAML, schema generation, runtime validation, and the `Usage` object itself

---

<!-- _header: "" -->
<!-- _class: lead part-feedback -->

# Part 3: Feedback

**Why this has been hard to split into small steps, and what I want input on**

---

<!-- header: "Context > Proposal > **Feedback**" -->

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

---

# My current framing

- The hard part is **not** that overlap and incomplete usage exist
- Those are already real problems in the current system
- The hard part is introducing a new source of truth above the current code structures
- That is why the change is broad, slow to split up, and hard to reason about incrementally

---

# Discussion prompt

1. **Would you keep pushing on this architecture**
2. **Would you solve the immediate pricing problems in a narrower way first**
3. **What is the simplest shape of this idea that would still be worth doing**
