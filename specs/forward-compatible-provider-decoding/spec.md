# Forward-Compatible Provider Decoding

**Currently published provider data must retain exactly its existing behavior.**
The pinned current-data fixtures are `prices/new_data/v2/data.json` (sha256
`06f100aaacf6ebaa76a536587fa5356e4ef21a0ba088dca2d5f5d78f15a9e88e`) and
`prices/new_data/v2/data_slim.json` (sha256
`59a2baa1a14a1c63bceec347c8cf7647f1df5c06a5809e24e0623246f3322de5`) at base revision
`bcb5cc5ee3865c31746109a981570029ec0453f8`. They must produce the same providers, matches, extraction results, prices,
validation outcomes, and absence of compatibility warnings before and after this change.

**Distinguishable future provider capabilities should not make understood siblings unusable.**
An installed package skips a new extractor, extractor mapping, extract-path step, match clause, price representation,
or price constraint only when the raw JSON unambiguously selects no representation that the package recognizes.

**Malformed recognized data in a retained capability must still fail.**
Once a raw value selects a recognized representation, missing fields, conflicting structural discriminators, and
invalid JSON kinds remain validation errors. An explicitly unrecognized `type` takes precedence at the typed extractor,
mapping, price, and constraint boundaries described below, even when recognized structural fields are also present.
Once such a capability or another distinguishably future capability is removed at its semantic owner boundary, its
descendants are opaque and are not classified or validated. These are intentional exceptions: the package cannot safely
interpret the interior of an explicitly future representation.

**Every skipped future capability must be observable.**
Successful decoding reports one compatibility warning for the boundary at which each future capability was skipped.
This is an independent product requirement rather than a consequence of projection.

**Python, JavaScript, and Go must retain the same projection.**
Given the same JSON provider array, all three runtimes retain and remove the same providers, models, extractors,
mappings, matches, conditional prices, and price-map entries.

**Projection runs before each runtime's existing provider-array decoder.** _(from "Distinguishable future provider capabilities", "Malformed recognized data in a retained capability must still fail")_
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

**Unsupported owners short-circuit descendant traversal.** _(from "Distinguishable future provider capabilities", "Malformed recognized data in a retained capability must still fail")_
An explicitly unsupported extractor is removed without inspecting its root, model path, or mappings. An unsupported
extractor root or model path removes the extractor without inspecting later fields or mappings. An explicitly
unsupported mapping is removed without inspecting its path or destination. An unsupported provider-level match removes
that match field; an unsupported model match removes the model without inspecting its prices. An unsupported
conditional constraint removes its entry without inspecting the nested price map. Each case emits only the owner-level
warning specified below. Retained owners continue traversal, so malformed recognized descendants still fail.

**Match recognition uses the seven existing structural discriminators.** _(from "Distinguishable future provider capabilities", "Malformed recognized data in a retained capability must still fail")_
The recognized keys are `and`, `or`, `contains`, `ends_with`, `equals`, `regex`, and `starts_with`. A non-object match is
malformed. An object with no recognized key is distinguishably future and unsupported. An object with more than one
recognized key is malformed. The presence of `contains`, `ends_with`, `equals`, `regex`, or `starts_with` selects that
recognized primitive form regardless of its value's JSON kind; a non-string value is retained and rejected by baseline
validation. The presence of `and` or `or` similarly selects the recognized boolean form; a non-array value is malformed.
Array children are classified recursively, and one unsupported child makes the entire enclosing boolean match
unsupported because retaining a subset could change its meaning.

**Unsupported matches are removed only at a semantic owner boundary.** _(from "Match recognition uses the seven existing structural discriminators")_
An unsupported `model_match` or `provider_match` removes that provider-level field. An unsupported model `match`
removes that model. An unsupported match nested in an array-match extract-path step makes that path unsupported and is
handled by the path's extractor or mapping owner. No additional warning is emitted for the nested match itself.

**Extractor recognition distinguishes explicitly typed additions from malformed current extractors.** _(from "Distinguishable future provider capabilities", "Malformed recognized data in a retained capability must still fail")_
Current extractors have no `type` member and require both `root` and `mappings`. An extractor object containing `type`,
regardless of that member's value or the presence of `root` or `mappings`, is distinguishably future and is removed.
An untyped object containing neither `root` nor `mappings` is also distinguishably future. An untyped object containing
exactly one of `root` and `mappings` is malformed. Non-object extractors and non-array `mappings` are malformed. Unknown
members on a recognized extractor do not affect recognition.

**Extractor mappings use `path` and `dest` as their recognized structural fields.** _(from "Distinguishable future provider capabilities", "Malformed recognized data in a retained capability must still fail")_
A mapping object containing `type`, regardless of that member's value or the presence of `path` or `dest`, is
distinguishably future and is removed. An untyped object containing neither `path` nor `dest` is also distinguishably
future. An untyped object containing exactly one of `path` and `dest` is malformed. A non-object mapping is malformed.
Unknown members on a recognized mapping do not affect recognition.

**Extract paths recognize strings and arrays of string or `array-match` steps.** _(from "Distinguishable future provider capabilities", "Malformed recognized data in a retained capability must still fail")_
A path that is a string is recognized. A path array is recognized when every step is a string or an object whose
`type` is exactly `array-match`; an object step with another or missing `type` makes the path distinguishably future.
An `array-match` step remains malformed if `field` is not a string, `match` is missing, or its recognized match is
malformed. A non-string, non-array path and a non-string, non-object array step are malformed.

**Unsupported extractor paths are removed at the smallest safe owner.** _(from "Distinguishable future provider capabilities", "Extract paths recognize strings and arrays of string or `array-match` steps")_
An unsupported extractor `root` or `model_path` removes that extractor. An unsupported mapping `path` removes that
mapping. When an extractor originally has one or more mappings and all are removed, the extractor is also removed, but
that cascading removal emits no additional warning. A recognized empty mapping list remains empty.

**Price maps distinguish future price objects from malformed tiered prices.** _(from "Distinguishable future provider capabilities", "Malformed recognized data in a retained capability must still fail")_
A JSON number selects the recognized scalar-price representation and remains baseline-decoded. `null`, booleans,
strings, and arrays are malformed. An object value containing `type`, regardless of that member's value or the presence
of `base` or `tiers`, is distinguishably future and its price key is removed. An untyped object containing neither
`base` nor `tiers` is also distinguishably future. An untyped object containing exactly one of `base` and `tiers`
selects the recognized tiered-price representation and remains malformed. Unknown members on an untyped object
containing both `base` and `tiers` do not affect recognition.

**Conditional-price recognition requires its existing `prices` field.** _(from "Malformed recognized data in a retained capability must still fail")_
A conditional-price entry must be an object containing `prices`; missing `prices`, a non-object entry, and a `prices`
value that is not an object remain malformed. Projection applies price-map recognition within each entry.

**Constraint recognition accepts the two existing structural or typed representations.** _(from "Distinguishable future provider capabilities", "Malformed recognized data in a retained capability must still fail", "Python, JavaScript, and Go must retain the same projection")_
Without `type`, an object containing any of `start_date`, `start_time`, or `end_time` selects the current structural
constraint; an object containing none is distinguishably future. With `type`, the string values `start_date` and
`time_of_date` select the corresponding current representation; any other value is distinguishably future regardless
of the presence of structural constraint fields. Once a representation is selected, missing required fields, mixed
start-date/time fields, and invalid values are malformed. A non-object constraint is malformed. A recognized constraint
is reduced to `type`, `start_date`, `start_time`, and `end_time` before baseline decoding so extension members cannot
create cross-runtime strictness differences.

**Unsupported prices preserve usable siblings.** _(from "Distinguishable future provider capabilities", "Price maps distinguish future price objects", "Constraint recognition accepts the two existing structural or typed representations")_
An unsupported price value removes only its price-map key. An unsupported constraint removes its whole conditional
entry. A conditional entry whose originally non-empty price map becomes empty is removed. A model whose originally
non-empty direct price map or conditional-price list becomes empty is removed. Other entries and models retain their
source order. A provider remains present even if all of its models are removed.

**Warnings use one exact contextual template.** _(from "Every skipped future capability must be observable")_
The message is `Unsupported <capability> variant at <path> for <context>; upgrade genai-prices for full support`.
Capability is one of `match`, `extractor`, `extractor mapping`, `price`, or `constraint`. Paths use zero-based forms such
as `providers[0].extractors[1]` and dot-separated field names. Context is `provider "<id>"` or `provider index <n>`,
followed for model-owned capabilities by `, model "<id>"` or `, model index <n>`. An ID is used only when it is a string
matching the ASCII pattern `^[A-Za-z0-9._:/-]+$`; it is quoted verbatim. Any missing, non-string, or other string ID
uses the index form, avoiding runtime-specific string escaping.

**Warning order follows a fixed depth-first traversal.** _(from "Warnings use one exact contextual template", "Python, JavaScript, and Go must retain the same projection")_
Providers use source-array order. Within each retained provider, projection visits `model_match`, `provider_match`,
extractors in source order, then models in source order. Within each retained extractor it visits `root`, `model_path`,
then mappings in source order. Within each retained model it visits `match`, then prices. Direct price-map keys use
lexical order. Conditional entries use source order; within each retained entry, projection visits `constraint` first
when present and, only when it is supported, visits nested price-map keys in lexical order. Boolean-match children use
source order. The short-circuit rules above suppress descendant warnings. Cascading removal of an empty extractor,
conditional list, price map, or model adds no warning beyond the warnings for the capabilities that caused it.

**Warnings are published only after the projected payload passes baseline decoding.** _(from "Every skipped future capability must be observable", "Malformed recognized data in a retained capability must still fail")_
If recognized data anywhere in the payload is invalid, provisional projection warnings are discarded. Python emits
the ordered messages as `UserWarning` after `_providers_from_raw` succeeds. JavaScript calls `console.warn` only after
normalization succeeds and immediately before activation. Go stores warnings only on a successfully constructed
calculator and appends them before existing calculation/extraction warnings in both result types.

**A compact shared integration fixture proves cross-runtime future projection.** _(from "Python, JavaScript, and Go must retain the same projection", "Warning order follows a fixed depth-first traversal")_
One provider-array fixture contains understood siblings plus one future match, extractor, mapping/path, price value, and
constraint. Each runtime asserts the exact retained raw/runtime shape, warning sequence, extraction result, and price.

**Focused tests pin every classification and removal boundary.** _(from "Malformed recognized data in a retained capability must still fail", "Match recognition uses the seven existing structural discriminators", "Extractor recognition distinguishes explicitly typed additions from malformed current extractors", "Extractor mappings use `path` and `dest` as their recognized structural fields", "Extract paths recognize strings and arrays of string or `array-match` steps", "Price maps distinguish future price objects from malformed tiered prices", "Constraint recognition accepts the two existing structural or typed representations", "Unsupported owners short-circuit descendant traversal", "Unsupported prices preserve usable siblings")_
Separate focused cases in each runtime cover every malformed-versus-future classifier, explicit-`type` precedence,
short-circuit, warning-context fallback, and cascading removal rule.

**The pinned current-data fixtures produce no projection warnings.** _(from "Currently published provider data must retain exactly its existing behavior", "Every skipped future capability must be observable")_
Each runtime projects the two exact base-revision payloads named above, asserts byte-for-byte-equivalent parsed data and
zero warnings, and then decodes them through the new boundary. Existing dataset and price suites pin downstream
matching, extraction, and calculation results.

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

**Unchanged behavior: Recognized provider arrays retain their validation and lifecycle semantics.** _(from "Currently published provider data must retain exactly its existing behavior", "Malformed recognized data in a retained capability must still fail")_
Python retains the fetch/root checks and shared-updater ownership in `packages/python/genai_prices/update_prices.py`;
JavaScript retains null/rejection/promise ordering in `packages/js/src/api.ts`; Go retains immutable construction and
`ErrInvalidData` wrapping in `packages/go/calculator.go`. Provider/model matching, extractor defaults, conditional-price
normalization, and error timing remain owned by the existing decoders. Only values classified above as
distinguishably future take the new skip-and-warn path.
