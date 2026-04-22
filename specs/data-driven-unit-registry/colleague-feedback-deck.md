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
    output_tokens: int | None = None
    input_audio_tokens: int | None = None
    cache_audio_read_tokens: int | None = None
    output_audio_tokens: int | None = None

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

# Price calculation has to handle overlapping tokens

```python
uncached_audio_input_tokens = usage.input_audio_tokens or 0
if cache_audio_read_tokens := (usage.cache_audio_read_tokens or 0):
    uncached_audio_input_tokens -= cache_audio_read_tokens

uncached_text_input_tokens = usage.input_tokens or 0
uncached_text_input_tokens -= uncached_audio_input_tokens
if cache_write_tokens := usage.cache_write_tokens:
    uncached_text_input_tokens -= cache_write_tokens
if cache_read_tokens := usage.cache_read_tokens:
    uncached_text_input_tokens -= cache_read_tokens

cached_text_input_tokens = usage.cache_read_tokens or 0
cached_text_input_tokens -= cache_audio_read_tokens
```

- This works for the current small set of fields
- It gets ugly if we add image, video, text-specific, or more cache variants

---

# Problem

- Many kinds of tokens are missing, e.g. image and video tokens
- Other kinds of usage are missing, e.g. tool calls or web search
- `AbstractUsage` is a `Protocol`, so adding fields is not a small local change
- Field names appear in several places, in both Python and JS
- Complex pricing logic for overlapping token types is hardcoded
- New hardcoded fields have to be added both to package code and to generated data outputs
- That creates an auto-update problem: runtime `data.json` can deliver prices for a new field before the installed package knows that field exists

> So there is a real extensibility problem, not just an aesthetic dislike of hardcoded fields

---

# One broad way to solve this is a unit registry

A unit registry means:

- there is a data file that declares the allowed units
- each unit says which usage key it reads from
- token units also describe how they overlap
- prices, usage extraction, and validation all derive from that registry

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

- In the full version of this idea, runtime `Usage`, `ModelPrice`, extractors, and validation all consult the registry
- Unit definitions also have to travel with runtime data and custom snapshots

---

# What that broader design buys us

- One declared contract for prices, usage, extractors, and validation
- Strong validation for repo-defined and runtime-defined units
- Unit metadata is self-describing
- Custom units are first-class at runtime
- The token decomposition algorithm can be generic

This is a coherent design

The question is whether the runtime complexity is worth it

---

# Why I am backing away from making the runtime registry-driven

- The runtime starts depending on a mutable unit schema
- `Usage` and `ModelPrice` stop feeling like normal objects
- Debugging goes through another layer of metadata lookups
- Auto-updated data and custom snapshots now change more than just prices
- The abstraction is solving too many problems at once

> It feels like the runtime is learning its own schema from data, and that feels iffy

---

# Narrower proposal

- Tokens stay special and built in
- Token overlap logic can still be dynamic internally
- Other units are scalar and simple
- Runtime behavior for scalar units is just exact-name matching and multiplication
- Repo-defined unit metadata can still exist, but only at build time

```python
input_total, output_total = calc_token_price(usage, model_price, TOKEN_UNITS)

for key, price in scalar_prices.items():
    total += price * scalar_usage.get(key, 0)
```

---

# What this actually simplifies

| Area                        | Registry-driven runtime     | Narrower proposal                          |
| --------------------------- | --------------------------- | ------------------------------------------ |
| Token overlap               | Dynamic                     | Dynamic                                    |
| Runtime schema              | Mutable and snapshot-driven | Fixed token logic plus simple scalar names |
| `Usage` / `ModelPrice`      | Registry-aware              | Mostly normal objects                      |
| Auto-updated data           | Prices and unit definitions | Just compiled price data                   |
| Repo validation             | Strong                      | Still strong for repo-defined units        |
| Runtime custom scalar units | First-class and structured  | First-class but intentionally weak         |

The simplification is real, but it is mainly a runtime architecture simplification

---

# What I am still unsure about

- How many token fields do we really want to hardcode publicly
- Whether repo-defined scalar units should look first-class at the API surface
- Whether runtime custom scalar units should use top-level keys or some explicit extra map
- How much validation we want for scalar units at runtime

The hard part that does **not** go away:

- token overlap still needs a real algorithm

---

# Build-time registry might still be useful

- Repo-defined scalar units can still have:
  - a canonical name
  - a description
  - schema validation for provider YAML files
  - optional normalization metadata such as `per`
- The build step can compile authored prices into a simple runtime representation

```yaml
scalar_units:
  web_search:
    description: Web search request
    per: 1000
```

The runtime library does not need this metadata to do `web_search * price`

---

# Open question 1 - normalization

Suppose provider YAML authors write:

```yaml
prices:
  web_search: 10
```

and that means "$10 per 1000"

But runtime custom prices are expected to be per 1:

```python
ModelPrice(web_search=0.01)
```

This is convenient for repo authoring, but it is also an easy place to make a 1000x mistake

---

# Open question 2 - should the authored key encode the normalization

Option A:

- Keep one key, e.g. `web_search`
- Put `per: 1000` only in metadata

Option B:

- Use an authored key like `web_search_kcount`
- Compile it to a runtime key like `web_search`

Tradeoff:

- Option A hides normalization
- Option B makes normalization visible, but introduces two names for one concept

---

# Open question 3 - what should happen to unpriced scalar usage

If usage includes `web_search=3` but the current model has no `web_search` price:

- Ignore it
- Warn
- Error

Related question:

- What is the set of valid scalar names at runtime
- Repo-defined names only
- All price keys currently present in the active snapshot
- Something else

---

# What I want feedback on

- Is "built-in token subsystem plus simple scalar units" the right direction
- Is the old runtime-registry proposal worth its extra runtime complexity
- Is normalization now the main remaining design risk
- Would you keep repo-defined scalar units first-class at the public API surface
- Is there a better narrow design that keeps the token algorithm generic without making the runtime schema dynamic
