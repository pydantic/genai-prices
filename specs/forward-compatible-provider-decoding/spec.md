# Forward-Compatible Provider Decoding

**Currently published provider data must retain exactly its existing behavior.**
The bundled provider array and the four v2 artifacts at the feature branch's base revision are the pinned current-data
fixtures. They must produce the same providers, matches, extraction results, prices, validation outcomes, and absence
of compatibility warnings before and after this change.

**Distinguishable future provider capabilities should not make understood siblings unusable.**
An installed package skips a new extractor, extractor mapping, extract-path step, match clause, price representation,
or price constraint only when the raw JSON unambiguously selects no representation that the package recognizes.

**Malformed recognized data must still fail.**
Once a raw value contains a recognized discriminator or any required structural field of a recognized representation,
missing fields, conflicting discriminators, and invalid JSON kinds remain validation errors. Forward compatibility does
not reinterpret malformed known data as a future capability.

**Every skipped future capability must be observable.**
Successful decoding reports one compatibility warning for the boundary at which each future capability was skipped.
This is an independent product requirement rather than a consequence of projection.

**Python, JavaScript, and Go must retain the same projection.**
Given the same JSON provider array, all three runtimes retain and remove the same providers, models, extractors,
mappings, matches, conditional prices, and price-map entries.

**Projection runs before each runtime's existing provider-array decoder.** _(from "Distinguishable future provider capabilities", "Malformed recognized data")_
Python projects the parsed list inside `packages/python/genai_prices/update_prices.py::UpdatePrices.fetch` before
`types._providers_from_raw`. JavaScript projects a non-null array inside
`packages/js/src/api.ts::activateProviderData` before its existing normalization. Go projects the top-level array in
`packages/go/calculator.go::NewCalculatorFromJSON` before unmarshalling to `[]provider` and calling
`Calculator.validate`. Projection returns raw projected data and ordered warnings; those existing decoders continue to
own defaults, recognized-value validation, and construction of runtime objects.

**Provider and model object requirements remain baseline validation concerns.** _(from "Projection runs before each runtime's existing provider-array decoder")_
Projection traverses `model_match`, `provider_match`, `extractors`, `models`, model `match`, and model `prices` only when
their enclosing values have the object/array kind required for traversal. A non-object provider/model, non-array
extractors/models/prices list, missing provider/model fields, or invalid metadata is left to the existing decoder and
therefore fails exactly where that runtime currently rejects it.

**Match recognition uses the seven existing structural discriminators.** _(from "Distinguishable future provider capabilities", "Malformed recognized data")_
The recognized keys are `and`, `or`, `contains`, `ends_with`, `equals`, `regex`, and `starts_with`. A non-object match is
malformed. An object with no recognized key is distinguishably future and unsupported. An object with more than one
recognized key is malformed. A primitive recognized match retains the whole object for baseline validation. An `and`
or `or` value must be an array; each child is classified recursively, and one unsupported child makes the entire
enclosing boolean match unsupported because retaining a subset could change its meaning.

**Unsupported matches are removed only at a semantic owner boundary.** _(from "Match recognition uses the seven existing structural discriminators")_
An unsupported `model_match` or `provider_match` removes that provider-level field. An unsupported model `match`
removes that model. An unsupported match nested in an array-match extract-path step makes that path unsupported and is
handled by the path's extractor or mapping owner. No additional warning is emitted for the nested match itself.

**Extractor recognition distinguishes explicitly typed additions from malformed current extractors.** _(from "Distinguishable future provider capabilities", "Malformed recognized data")_
Current extractors have no `type` member and require both `root` and `mappings`. An extractor object containing `type`,
or containing neither `root` nor `mappings`, is distinguishably future and is removed. An object containing exactly
one of `root` and `mappings` is malformed. Non-object extractors and non-array `mappings` are malformed. Unknown members
on a recognized extractor do not affect recognition.

**Extractor mappings use `path` and `dest` as their recognized structural fields.** _(from "Distinguishable future provider capabilities", "Malformed recognized data")_
A mapping object containing an explicit `type`, or containing neither `path` nor `dest`, is distinguishably future and
is removed. An object containing exactly one of `path` and `dest` is malformed. A non-object mapping is malformed.
Unknown members on a recognized mapping do not affect recognition.

**Extract paths recognize strings and arrays of string or `array-match` steps.** _(from "Distinguishable future provider capabilities", "Malformed recognized data")_
A path that is a string is recognized. A path array is recognized when every step is a string or an object whose
`type` is exactly `array-match`; an object step with another or missing `type` makes the path distinguishably future.
An `array-match` step remains malformed if `field` is not a string, `match` is missing, or its recognized match is
malformed. A non-string, non-array path and a non-string, non-object array step are malformed.

**Unsupported extractor paths are removed at the smallest safe owner.** _(from "Extract paths recognize strings and arrays of string or `array-match` steps")_
An unsupported extractor `root` or `model_path` removes that extractor. An unsupported mapping `path` removes that
mapping. When an extractor originally has one or more mappings and all are removed, the extractor is also removed, but
that cascading removal emits no additional warning. A recognized empty mapping list remains empty.

**Price maps distinguish future price objects from malformed tiered prices.** _(from "Distinguishable future provider capabilities", "Malformed recognized data")_
Existing scalar price values remain baseline-decoded. An object value containing an explicit `type`, or containing
neither `base` nor `tiers`, is distinguishably future and its price key is removed. An object containing exactly one of
`base` and `tiers` selects the recognized tiered-price representation and remains malformed. Unknown members on an
object containing both `base` and `tiers` do not affect recognition.

**Conditional-price recognition requires its existing `prices` field.** _(from "Malformed recognized data")_
A conditional-price entry must be an object containing `prices`; missing `prices`, a non-object entry, and a `prices`
value that is not an object remain malformed. Projection applies price-map recognition within each entry.

**Constraint recognition accepts the two existing structural or typed representations.** _(from "Distinguishable future provider capabilities", "Malformed recognized data")_
Without `type`, an object containing any of `start_date`, `start_time`, or `end_time` selects the current structural
constraint; an object containing none is distinguishably future. With `type`, the string values `start_date` and
`time_of_date` select the corresponding current representation; another string or a non-string `type` is
distinguishably future. Once selected, missing required fields, mixed start-date/time fields, invalid values, and a
non-object constraint are malformed. A recognized constraint is reduced to `type`, `start_date`, `start_time`, and
`end_time` before baseline decoding so extension members cannot create cross-runtime strictness differences.

**Unsupported prices preserve usable siblings.** _(from "Price maps distinguish future price objects", "Constraint recognition accepts the two existing structural or typed representations")_
An unsupported price value removes only its price-map key. An unsupported constraint removes its whole conditional
entry. A conditional entry whose originally non-empty price map becomes empty is removed. A model whose originally
non-empty direct price map or conditional-price list becomes empty is removed. Other entries and models retain their
source order. A provider remains present even if all of its models are removed.

**Warnings use one exact contextual template.** _(from "Every skipped future capability must be observable")_
The message is `Unsupported <capability> variant at <path> for <context>; upgrade genai-prices for full support`.
Capability is one of `match`, `extractor`, `extractor mapping`, `price`, or `constraint`. Paths use zero-based forms such
as `providers[0].extractors[1]` and dot-separated field names. Context is `provider "<id>"` or `provider index <n>`,
followed for model-owned capabilities by `, model "<id>"` or `, model index <n>`. IDs use JSON string escaping.

**Warning order follows a fixed depth-first traversal.** _(from "Warnings use one exact contextual template", "Python, JavaScript, and Go must retain the same projection")_
Providers, extractors, mappings, models, conditional entries, and boolean-match children use source-array order.
Provider match fields are visited as `model_match`, then `provider_match`; extractor fields as `root`, then
`model_path`, then mappings; model fields as `match`, then prices. Direct price-map keys are visited in lexical order.
Cascading removal of an empty extractor, conditional list, price map, or model adds no warning beyond the warnings for
the capabilities that caused it.

**Warnings are published only after the projected payload passes baseline decoding.** _(from "Every skipped future capability must be observable", "Malformed recognized data")_
If recognized data anywhere in the payload is invalid, provisional projection warnings are discarded. Python emits
the ordered messages as `UserWarning` after `_providers_from_raw` succeeds. JavaScript calls `console.warn` only after
normalization succeeds and immediately before activation. Go stores warnings only on a successfully constructed
calculator and appends them before existing calculation/extraction warnings in both result types.

**A compact shared fixture proves cross-runtime future projection.** _(from "Python, JavaScript, and Go must retain the same projection", "Warning order follows a fixed depth-first traversal")_
One provider-array fixture contains understood siblings plus one future match, extractor, mapping/path, price value, and
constraint. Each runtime asserts the exact retained raw/runtime shape, warning sequence, extraction result, and price.
Separate focused cases cover every malformed-versus-future classifier and cascading removal rule.

**The pinned current-data fixtures produce no projection warnings.** _(from "Currently published provider data must retain exactly its existing behavior", "Every skipped future capability must be observable")_
Each runtime decodes the base revision's full and slim v2 arrays through the new boundary, asserts zero warnings, and
compares the decoded provider data with its pre-projection baseline. Existing dataset and price suites then pin
downstream matching, extraction, and calculation results.

**Failed decoding preserves the prior active state.** _(from "Currently published provider data must retain exactly its existing behavior", "Warnings are published only after the projected payload passes baseline decoding")_
Context: Python's shared updater installs only a returned `DataSnapshot`; JavaScript's `activateProviderData` assigns
only after normalization; Go constructs immutable calculators. The extraction retains those transaction boundaries:
Python returns no replacement snapshot, JavaScript retains the previously active provider array, and Go returns no
calculator when recognized data is invalid.

---

**Scope exclusions: Only the existing provider-array root is accepted.**
This extraction does not accept a wrapped object or any other new payload root.

**Dynamic unit definitions are excluded.**
All three runtimes continue using their bundled unit definitions; there is no unit evolution or paired registry/provider
activation.

**Schema and Git compatibility enforcement are excluded.**
This extraction does not compare schemas or revisions and adds no build or CI compatibility job.

**Publication and package generation are excluded.**
No generated data, generated schema, package registry, default URL, frozen-artifact policy, or release behavior changes.

---

**Unchanged behavior: Recognized provider arrays retain their validation and lifecycle semantics.** _(from "Currently published provider data must retain exactly its existing behavior", "Malformed recognized data must still fail")_
Python retains the fetch/root checks and shared-updater ownership in `packages/python/genai_prices/update_prices.py`;
JavaScript retains null/rejection/promise ordering in `packages/js/src/api.ts`; Go retains immutable construction and
`ErrInvalidData` wrapping in `packages/go/calculator.go`. Provider/model matching, extractor defaults, conditional-price
normalization, and error timing remain owned by the existing decoders. Only values classified above as
distinguishably future take the new skip-and-warn path.
