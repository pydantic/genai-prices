# Unit Registry — Reference

**Date:** 2026-03-23
**Companion spec:** `2026-03-23-unit-registry-spec.md`

This document contains coverage analysis, algorithm details, and edge case research that supports the Unit Registry spec. It is not a specification — it is reference material.

---

## 1. Token Units — Coverage Analysis

Every modality defines all four slots (input, output, cache read, cache write) even where no provider currently uses them. This keeps the registry symmetric. Models simply don't define prices for unused units.

**Currently used in the wild (at least one provider):**

- `input_mtok`, `output_mtok`, `cache_read_mtok`, `cache_write_mtok` — all providers
- `input_audio_mtok`, `output_audio_mtok`, `cache_read_audio_mtok` — OpenAI Realtime, Google
- `input_image_mtok`, `output_image_mtok`, `cache_read_image_mtok` — OpenAI gpt-image, Google
- `input_video_mtok`, `cache_read_video_mtok` — Google
- `input_text_mtok`, `output_text_mtok` — image/audio-primary models (catch-all convention)

**Defined but not yet used by any provider:**

- `cache_write_{text,audio,image,video}_mtok` — no provider differentiates cache write by modality
- `cache_read_text_mtok` — text is the catch-all; only needed if text cache rate differs from catch-all
- `output_video_mtok` — no provider has token-based video output (Sora is per-second)

---

## 2. Non-Token Units — Coverage Analysis

**tool_calls:**

- `web_search` — OpenAI ($10/1K calls), Anthropic ($10/1K searches). Billed per individual search invocation.
- `file_search` — OpenAI ($2.50/1K calls).
- `google_search_grounding` — Google ($35/1K grounded prompts). Billed per request that returns grounding results, not per individual search within a request.
- `google_maps_grounding` — Google ($14-25/1K queries).
- `google_data_grounding` — Google ($2.50/1K requests). "Grounding with Your Data."

**images:**

- `image_generated` — Google modality-based pricing ($0.04/image for Gemini 2.0 Flash). Non-token alternative for image output. Some models offer BOTH token-based (`output_image_mtok`) and per-image (`image_generated`) pricing; a given model uses one or the other.

**audio_seconds:**

- `input_audio_second` — Google modality-based ($0.000025/second). Alternative to `input_audio_mtok`.
- `output_audio_second` — not currently used but defined for symmetry.

**video_seconds:**

- `input_video_second` — Google modality-based ($0.0000387/second). Alternative to `input_video_mtok`.
- `output_video_second` — OpenAI Sora ($0.05-$0.70/second depending on model and resolution). Resolution is a `when` condition parameter, not a dimension.

**characters:**

- `input_mchar` — Google modality-based ($0.0375/M characters). Alternative to token-based text pricing.
- `output_mchar` — Google modality-based ($0.15/M characters).

**training_tokens:**

- `training_mtok` — OpenAI fine-tuning (e.g., $25/M tokens for gpt-4o), Google tuning (e.g., $3/M for Gemini 2.0 Flash). Total training tokens = dataset tokens x epochs.

**training_hours:**

- `training_hour` — OpenAI fine-tuning ($100/hr for some models). Alternative to per-token training billing.

---

## 3. Edge Cases in Real-World Pricing

**Free tier quotas:** Storage (1 GB free), compute (1,550 hrs/month free), grounding (1,500/day free) all have marginal free tiers that the condition system can't express. See Section 5.1.

**Minimum billing periods:** Anthropic code execution has a 5-minute minimum. Caller rounds up before constructing the usage object. See Section 5.2.

**Conditional tool pricing:** Anthropic code execution is free when used with web_search or web_fetch. Expressible as `when: {has_web_search: true}` with `code_execution_hour: 0`, though adding a parameter for "other tools present" is a stretch.

**Per-turn billing (Google LiveAPI):** Each turn re-charges accumulated context from previous turns. Not a unit definition problem — the units and prices are standard; the usage values are inflated by design. An extraction/caller concern.

---

## 4. Decomposition Algorithm

### 4.1 Containment Poset

Unit A **contains** unit B if B's dimension assignments are a strict superset of A's. Equivalently, B is "more specific" — it pins every dimension A pins (to the same value) plus at least one more.

```
input_mtok  {direction: input}
├── cache_read_mtok       {direction: input, cache: read}
│   └── cache_read_audio_mtok  {direction: input, cache: read, modality: audio}
├── cache_write_mtok      {direction: input, cache: write}
├── input_audio_mtok      {direction: input, modality: audio}
│   └── cache_read_audio_mtok  {direction: input, cache: read, modality: audio}
├── input_image_mtok      {direction: input, modality: image}
└── input_text_mtok       {direction: input, modality: text}
```

Note this is a **lattice**, not a tree: `cache_read_audio_mtok` has two parents (`cache_read_mtok` and `input_audio_mtok`). This is handled correctly by inclusion-exclusion.

### 4.2 Decomposition via Inclusion-Exclusion

The **leaf value** of a unit (the portion not claimed by any more specific unit) is computed by standard Mobius inversion on the containment poset.

Concrete example — leaf value of `input_mtok`:

```
input_mtok_leaf = input_mtok
  - cache_read_mtok - cache_write_mtok - input_audio_mtok - input_image_mtok - input_text_mtok
  + cache_read_audio_mtok  (subtracted twice via cache_read and input_audio, add back)
```

The general formula: for each unit U contained in the target, multiply its usage value by the Mobius function `mu(target, U)`, which equals `(-1)^k` where k is the number of additional dimensions U pins beyond the target.

> **Note (incomplete formula):** The formula above is incomplete. It omits `input_video_mtok` from the children (depth-1 subtractions) and only shows 1 of 8 grandchild corrections (`cache_read_audio_mtok`). The full set of depth-1 children of `input_mtok` is: `cache_read_mtok`, `cache_write_mtok`, `input_audio_mtok`, `input_image_mtok`, `input_text_mtok`, `input_video_mtok`. The depth-2 grandchildren that need adding back (each subtracted twice) include: `cache_read_audio_mtok`, `cache_read_image_mtok`, `cache_read_text_mtok`, `cache_read_video_mtok`, `cache_write_audio_mtok`, `cache_write_image_mtok`, `cache_write_text_mtok`, `cache_write_video_mtok`. The complete formula for the full registry would be:
>
> ```
> input_mtok_leaf = input_mtok
>   - cache_read_mtok - cache_write_mtok
>   - input_audio_mtok - input_image_mtok - input_text_mtok - input_video_mtok
>   + cache_read_audio_mtok + cache_read_image_mtok + cache_read_text_mtok + cache_read_video_mtok
>   + cache_write_audio_mtok + cache_write_image_mtok + cache_write_text_mtok + cache_write_video_mtok
> ```

### 4.3 Precomputation from Registry

The decomposition coefficients depend only on the unit definitions — not on usage values or prices. Given the registry, a helper can precompute for each unit:

- **Children**: which units it directly contains
- **Descendants**: transitive closure
- **Decomposition formula**: the set of (unit, coefficient) pairs for computing the leaf value

This precomputation happens once when the registry is loaded. At price-calculation time, the engine just applies the precomputed formula to the actual usage values.

> **Note (scope correction):** Precomputation as described here is incomplete. The decomposition formula must be scoped to the set of units that have prices for the current model, not all registered units. If a model does not price `input_audio_mtok`, then audio tokens should NOT be subtracted from the catch-all `input_mtok` — they are part of the catch-all's leaf value for that model. The precomputed "full registry" formula is a starting point, but at calculation time the engine must filter to only units with resolved prices and recompute (or mask) the formula accordingly. Example: a text-only model prices only `input_mtok` and `output_mtok`. The decomposition formula for `input_mtok` should be just `input_tokens` with no subtractions, because no more-specific unit has a price. If the full-registry formula were applied blindly, it would subtract `input_audio_tokens` (if reported) from the catch-all, but there's no audio price to charge those tokens to — they'd be lost.

### 4.4 Registry-Level Helpers

These operate on unit definitions alone (no usage or prices needed):

| Helper                        | Input     | Output                                       |
| ----------------------------- | --------- | -------------------------------------------- |
| `descendants(unit)`           | A unit ID | All units it contains (transitively)         |
| `ancestors(unit)`             | A unit ID | All units that contain it                    |
| `decomposition_formula(unit)` | A unit ID | List of `(unit_id, coefficient)` pairs       |
| `is_leaf(unit)`               | A unit ID | Whether any registered unit is more specific |

### 4.5 Usage-Level Helpers

These take usage data and apply the precomputed formulas:

| Helper                    | Input                 | Output                                           |
| ------------------------- | --------------------- | ------------------------------------------------ |
| `total(unit, usage)`      | A unit + usage values | The reported usage for that unit (direct lookup) |
| `leaf_value(unit, usage)` | A unit + usage values | Usage not claimed by any more specific unit      |

---

## 5. Known Limitations (Detailed)

### 5.1 Marginal / Stepped Pricing

Our condition system selects a **single price per unit** via first-match. This is "all-or-nothing" — either all usage of a type is free, or all of it is charged. It cannot express "first N free, remainder at $X."

**Where this comes up:**

- Storage free tiers: OpenAI 1 GB free file search storage, then $0.10/GB-day
- Compute free tiers: Anthropic 1,550 free code execution hours/month, then $0.05/hr
- Grounding free tiers: Google 1,500 free grounded prompts/day
- Hypothetical future: volume discounts with per-unit marginal rates

**Note:** The _existing_ `TieredPrices` in the current codebase also doesn't handle this — its tiers are all-or-nothing too (e.g., "above 200K input tokens, ALL tokens get the higher rate"). So this isn't a regression.

**Example (BROKEN):**

```yaml
# BROKEN — this is all-or-nothing, not marginal
prices:
  - when:
      file_search_storage_gb_day: { lte: 1 }
    values:
      file_search_storage_gb_day: 0 # free if under 1 GB-day
  - values:
      file_search_storage_gb_day: 0.10 # full price if over
```

This gives the wrong answer for 2 GB-days: it selects the $0.10 rate and charges $0.20. The correct answer is $0.10 (only 1 GB-day over the free allowance). The condition selects a _single rate for all units of that type_ — it can't split usage across two rates.

**Workaround:** The caller subtracts the free allowance before constructing the usage object: `{file_search_storage_gb_day: max(0, actual - 1)}`. Shifts complexity to the caller but gives correct results.

**Future:** A `tiers` concept within a price entry could split usage at thresholds:

```yaml
# Hypothetical
file_search_storage_gb_day:
  tiers:
    - up_to: 1
      price: 0
    - price: 0.10
```

This is a well-understood concept (AWS-style tiered pricing) but adds complexity to the pricing engine. Worth considering if marginal pricing becomes common across more unit types.

### 5.2 Minimum Billing Periods

Anthropic code execution has a 5-minute minimum — a 1-second execution costs the same as 5 minutes. This is a rounding/floor operation on the usage count, not a pricing rule. The caller handles it before constructing the usage object.

### 5.3 Google LiveAPI Per-Turn Billing

Google's LiveAPI bills per turn and charges for the entire accumulated context window (current turn + previous turns). This is a different billing model from standard per-request pricing — the same tokens are charged again on subsequent turns.

This doesn't affect unit definitions or prices (it's still per-token), but it would affect how usage is extracted and passed to `calc_price`. Each turn's usage includes previously-billed tokens.

**Deferred.** Extraction-level concern, not a data model issue.
