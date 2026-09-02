# Forward-Compatible Provider Decoding

**Currently published provider data must retain exactly its existing behavior.**
The extraction is safe to merge before v3 exists: the bundled and remotely published v2 provider arrays produce the
same providers, matches, extraction results, prices, errors, and absence of compatibility warnings as before.

**Distinguishable future provider capabilities should not make understood siblings unusable.**
A payload may add a new extractor, extractor mapping, extract-path step, match clause, price representation, or price
constraint that an installed package does not yet understand. When the new representation is distinguishable from all
recognized representations, the package keeps the rest of the provider data that it can interpret safely.

**Malformed recognized data must still fail.**
Forward compatibility is not error recovery for known representations. A value that selects or partially resembles a
recognized representation but violates that representation's required shape is passed to existing validation or
rejected with equivalent strictness; it is never reclassified as a future capability merely to make the payload load.

**Python, JavaScript, and Go implement the same projection policy.**
Each runtime applies the policy before its existing provider-array decoder or validator. The implementations may use
language-appropriate internal representations, but shared fixtures pin the same retained providers, models,
extractors, mappings, prices, warning order, and malformed-input outcomes.

**Existing provider-array ingestion performs forward projection before baseline decoding.** _(from "Distinguishable future provider capabilities", "Malformed recognized data", "Python, JavaScript, and Go implement the same projection policy")_
Python applies projection in `UpdatePrices.fetch()`, JavaScript applies it when `setProviderData()` activates a
non-null provider array, and Go applies it in `NewCalculatorFromJSON()`. No new payload root is accepted. Projection
returns a sanitized provider array plus ordered compatibility warnings, then the existing decoder performs normal
defaulting, normalization, and validation.

**Projection skips the smallest independently unusable capability.** _(from "Distinguishable future provider capabilities")_
An unsupported provider-level match is removed while the provider remains usable through its other matching routes.
An unsupported extractor is removed. An unsupported mapping is removed, and an extractor that originally had mappings
is removed if none remain usable. An unsupported model match removes that model. An unsupported price value is removed
from its price map; an unsupported constraint removes its conditional-price entry; and a model with a non-empty price
definition from which no usable price remains is removed. A nested unsupported match invalidates its whole enclosing
boolean match because retaining only some children could broaden or narrow matching.

**Recognized discriminators take precedence over unknown members.** _(from "Distinguishable future provider capabilities", "Malformed recognized data")_
Unknown optional object members do not turn an otherwise recognized representation into a future variant. A match with
exactly one recognized discriminator remains recognized even when it has extension members. Multiple recognized match
discriminators are ambiguous and fail. A `type` value explicitly naming an unrecognized extractor, mapping,
extract-path step, price, or constraint makes that capability distinguishably unsupported.

**Compatibility warnings identify every skipped boundary deterministically.** _(from "Projection skips the smallest independently unusable capability", "Python, JavaScript, and Go implement the same projection policy")_
Warnings name the capability, its provider-array path, the provider/model identifier when available, and recommend
upgrading `genai-prices`. Warnings follow source order. Python emits `UserWarning` during fetch, JavaScript uses
`console.warn` during activation, and Go stores warnings on the constructed calculator and appends them to both price
calculation and usage-extraction results. Unknown optional members that do not require projection emit no warning.

**Failed recognized data never replaces active data.** _(from "Malformed recognized data", "Existing provider-array ingestion performs forward projection before baseline decoding")_
Python returns no replacement snapshot, JavaScript retains the previously active providers, and Go returns no
calculator. Existing updater and promise lifecycle rules determine how the failure is surfaced; projection introduces
no separate activation state.

**The current published provider array is a zero-warning parity fixture.** _(from "Currently published provider data must retain exactly its existing behavior", "Python, JavaScript, and Go implement the same projection policy")_
Each runtime decodes the repository's current v2 payload through the new boundary and proves that no capability is
removed and no compatibility warning is produced. Existing dataset and price suites continue to pin downstream
matching, extraction, and calculation behavior.

---

**Scope exclusions: Wrapped v3 data and dynamic unit registries are not introduced.**
This change accepts only the existing provider-array root and continues using bundled unit definitions. It does not add
wrapped `{units, providers}` decoding, unit evolution, paired activation, or runtime-added usage and price keys.

**Schema evolution enforcement is deferred.**
This change does not compare JSON Schemas or Git revisions and does not add a compatibility build or CI job.

**Publication and package generation are unchanged.**
No generated data, schema, package registry, default URL, frozen-artifact policy, or release behavior changes.

---

**Unchanged behavior: Existing recognized provider arrays retain their validation and lifecycle semantics.**
Provider matching, model matching, extractor defaults, conditional-price normalization, error timing, updater ownership,
snapshot/promise replacement, and Go calculator immutability remain governed by their current implementations. Only a
distinguishable unsupported future capability takes the new skip-and-warn path.
