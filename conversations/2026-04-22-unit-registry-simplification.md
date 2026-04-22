# Unit Registry Simplification Exploration

Captured on 2026-04-22.

Codebase state referenced during this discussion: commit `971df9567f08d54eb8d1301a7143968dea8f8cc8` on branch `feat/token-unit-registry`.

Key paths examined during the discussion:

- `specs/data-driven-unit-registry/spec.md`
- `packages/python/genai_prices/types.py`
- `packages/python/genai_prices/decompose.py`
- `packages/python/genai_prices/units.py`
- `packages/js/src/types.ts`
- `packages/js/src/engine.ts`
- `prices/units.yml`
- `prices/src/prices/package_data.py`
- `prices/providers/openai.yml`

## Original Problem And Motivation

The current detailed unit-registry spec felt overcomplicated and over-abstract. The core concern was that the spec was trying to make a single runtime abstraction solve too many different problems at once:

- token overlap/decomposition
- repo authoring/schema validation
- runtime custom units
- runtime custom snapshots and dynamic public API shape
- extractor destination validation

The user was concerned that this created "schema that changes at runtime", which felt hard to reason about in code, hard to debug, and hard for future readers to follow.

The motivating question became: what simplification is actually being gained if token overlap is still hard and requires some dynamic behavior internally?

## Important Research Findings From Source Inspection

### 1. The current branch is not the same thing as the detailed spec

The branch `feat/token-unit-registry` contains an older, partial attempt at the feature, predating the current detailed spec. It is not "the spec implemented". The user explicitly clarified that the right comparison is the diff from `main`, not the branch state alone.

### 2. `main` is much more hard-coded than the branch

Comparing `main...HEAD` showed that `main` has:

- hard-coded token fields in `Usage`, `ModelPrice`, and extractor destination types
- hard-coded token subtraction logic in Python and JS price calculation
- no runtime unit registry
- no decomposition engine
- no `prices/units.yml`

The branch adds:

- token-only unit metadata in `prices/units.yml`
- generated `units_data.json`
- runtime `units.py` / `units.ts`
- decomposition code in Python and JS
- ancestor-coverage validation

But the branch still keeps:

- hard-coded `Usage`
- hard-coded `ModelPrice`
- hard-coded extractor destination literal types
- special-cased `requests_kcount`

So the branch is a hybrid: generic token decomposition with mostly fixed public APIs.

### 3. The actual simplification target is not token math

The token-overlap problem remains genuinely hard in both designs. The simplification does not really eliminate the token algorithm. The real simplification is removing runtime schema dynamism:

- no mutable unit registry on `DataSnapshot`
- no runtime-defined `Usage`/`ModelPrice` surface driven by registry data
- no need for unit definitions to travel with runtime auto-updated price data
- no need for runtime registry validation as a core path

This became the most concrete articulation of what is gained by simplification.

## Approaches Considered

### Approach A: Full runtime unit registry from the detailed spec

Summary:

- units are data, not code
- runtime `UnitRegistry` on snapshots
- `Usage`, `ModelPrice`, extractor destinations, and validation all consult the runtime registry
- unit definitions travel with prices in runtime data
- custom units are first-class at runtime

Pros:

- single declared contract across prices, usage, extractors, and validation
- strong validation
- unit metadata is self-describing
- custom units can be first-class and portable
- consistent across Python/JS/runtime updates

Cons:

- runtime schema changes with snapshot data
- much harder debugging and mental model
- multiple layers of runtime indirection
- over-general for a problem that is mostly token overlap plus scalar extras
- forces many core runtime objects to become registry-aware and dynamic

Assessment:

- technically coherent but too expensive and abstract for the problem.

### Approach B: Stay close to `main` and keep token logic fully hard-coded

Summary:

- keep fixed fields
- manually code all token overlap cases with explicit subtraction logic

Pros:

- simple runtime mental model
- easy to step through
- obvious code paths

Cons:

- scaling that manual logic to a larger fixed token lattice is unattractive
- adding more token variants means more bespoke code
- hard-coded chain becomes error-prone if expanded to many modalities/variants

Assessment:

- acceptable for the current small set of token fields on `main`, but poor if the fixed token vocabulary expands significantly.

### Approach C: Fixed built-in token lattice/table in code, dynamic token algorithm, no runtime registry

Summary:

- tokens are special and built-in
- token logic may still be dynamic internally (driven by a fixed code constant/table)
- runtime users do not mutate token definitions
- non-token units are scalar and simple

Pros:

- preserves dynamic internal token handling without runtime schema dynamism
- keeps token semantics code-defined and stable
- easier debugging than snapshot-driven runtime metadata
- most of the value of the branch's token decomposition without the full runtime registry

Cons:

- token complexity still exists
- still requires careful design of the fixed token lattice and helper code
- can feel only partially simplified because the hard part is still hard

Assessment:

- this emerged as the most promising direction for token handling.

### Approach D: Scalar non-token units with exact-name matching and no runtime registry

Summary:

- non-token custom units have no overlap semantics
- `usage * price` by exact name
- no runtime registry required for these scalar units

Pros:

- extremely simple runtime model
- custom units are easy to add
- no decomposition, no family grouping, no runtime metadata lookup

Cons:

- weak typo safety
- string names provide identity but not semantic meaning
- risks collisions or unclear meaning across providers/users
- custom units become second-class unless extra tooling is added

Assessment:

- viable if constrained to strictly scalar, non-overlapping, "per one" semantics.

### Approach E: Scalar units boxed into `extra_usage` / `extra_prices`

Summary:

- built-ins remain top-level, customs go into explicit dicts

Pros:

- clearer internal separation
- easier typing and debugging
- avoids blurring built-ins and dynamic keys

Cons:

- makes normal repo-defined units visibly second-class
- less ergonomic for the common case
- fights the goal that normal repo-defined units should look first-class to users

Assessment:

- useful as an internal implementation idea, but not desirable as the public surface if first-class UX for normal units is a priority.

### Approach F: First-class top-level scalar units for users, special-cased only internally

Summary:

- top-level user-facing names like `web_search`
- internals distinguish fixed token keys from scalar keys
- no runtime registry needed for scalar semantics

Pros:

- good UX for the normal case
- keeps repo-defined non-token units looking first-class
- runtime remains much simpler than the full spec

Cons:

- weaker namespace hygiene
- requires internal conventions to distinguish built-ins from scalar extras
- still easier to drift toward "everything is dynamic" if discipline is lost

Assessment:

- this became the best compromise once the user emphasized prioritizing the normal case over runtime customization ergonomics.

## Major Pivots During The Discussion

### Pivot 1: From "full spec vs simplification" to "what does simplification actually remove?"

Initially the simplification looked questionable because token overlap still needs algorithmic handling. The more precise conclusion became:

- simplification does not eliminate token math
- simplification removes runtime schema/meta-system complexity

That was the key reframing.

### Pivot 2: From "extra maps are cleaner" to "top-level first-class units are probably better for the normal case"

Initially there was a preference for `extra_usage` / `extra_prices` maps to keep implementation boundaries clean. The user pushed back that the normal case matters more than runtime-defined cases, and that repo-defined units like `web_search` should look first-class.

This changed the recommendation:

- explicit extra maps may still help internally
- but they should not dominate the user-facing design
- top-level first-class scalar units are acceptable if internals still route them through simple scalar logic

### Pivot 3: Extractors are secondary for runtime custom units

There was early over-focus on extractor design. The user clarified:

- repo-defined extractors are important and should stay strongly validated
- runtime-defined extractors should be possible but are not strategically important
- custom usage can always be extracted by user code directly

This narrowed the design pressure on runtime custom-unit extractor support.

### Pivot 4: Build-time registry remains useful even if runtime registry disappears

The discussion moved from "remove registry" to a more precise split:

- keep a build-time unit registry for repo-defined units
- use it for descriptions, allowed names, schema generation, and possibly normalization metadata
- do not require the runtime library engine to load or consult it for scalar unit behavior

This was an important middle ground.

### Pivot 5: `per`/normalization became the main remaining concern

Once the runtime-registry complexity was stripped back, the sharpest remaining concern became normalization:

- if repo-defined units are authored as per-1000 but runtime sees per-1, then the same unit name has different implied meanings in different places
- that risks 1000x copy/paste mistakes and review/debug confusion

This replaced earlier concerns as the main remaining design risk in the simplified direction.

## Current Leaning / Tentative Decisions

The conversation did not finalize a new spec, but the current direction is:

- Token units remain special and built-in.
- Token overlap logic may still be dynamic internally, but token definitions should be fixed in code rather than mutated through a runtime unit registry.
- Runtime schema dynamism is viewed as the main thing to avoid.
- Non-token units should be simple scalar units with exact-name matching and no decomposition.
- Repo-defined non-token units should ideally look first-class at the public surface, not obviously second-class.
- Build-time registry remains useful for repo-defined units and schema generation, but runtime should not depend on it for scalar unit behavior.
- Runtime-defined custom scalar units are still important.
- Runtime-defined extractors should be possible but are secondary.

## Remaining Open Questions

### 1. Normalization / `per`

This is the biggest unresolved issue.

Current idea under discussion:

- repo-defined scalar units may carry build-time metadata like `description` and `per`
- provider YAML authors could write convenient prices like `web_search: 10` meaning "$10 per 1000"
- build step would normalize to per-1 runtime prices like `web_search: 0.01`

Concern:

- the same unit key would have different implied semantics in authoring vs runtime
- this is error-prone, especially for copy/paste into runtime custom prices

Potential mitigation:

- authoring-time price keys encode normalization explicitly, e.g. `web_search_kcount`
- runtime usage key remains `web_search`
- build step normalizes to runtime per-1

This reduces hidden normalization but introduces two names for one concept.

### 2. How strict should usage validation be for scalar units?

Open question:

- if mapping-based usage is strict, what happens when usage contains a known scalar unit that is unpriced for the current model?

Possible behaviors discussed:

- ignore
- warn
- error

This affects whether callers can safely supply richer usage than a specific model currently prices.

### 3. Scope of the "known scalar units" set at runtime

If runtime keeps any implicit allowed-name set for scalar units, what is it derived from?

Possibilities discussed:

- all repo-defined scalar price keys compiled into the package
- all price keys currently present in the active snapshot
- some union of repo-defined keys and runtime-defined keys already seen in prices

Concern:

- "known globally" is not the same as "priced for this model"
- the scope of the set changes validation behavior and error reporting

### 4. Public top-level fields vs internal storage

The current leaning is that normal repo-defined units should look first-class publicly. Still open:

- should internals store scalar custom units separately even if the public API exposes them top-level?
- or should runtime objects really become top-level dynamic bags of keys?

The conversation leaned toward "publicly first-class, internally may still distinguish tokens from scalars", but this was not resolved into a concrete object model.

## Things Explicitly Deferred

- Final rewrite of `specs/data-driven-unit-registry/spec.md`
- Any code changes implementing the new design
- Deciding exactly how runtime custom extractors should work
- Deciding whether repo-defined scalar unit authoring keys should encode normalization explicitly
- Deciding how strict scalar-unit usage validation should be

## Rejected / De-emphasized Ideas

- Full runtime-mutated `UnitRegistry` as the central runtime abstraction
- Making all units, including tokens and scalar custom units, equally registry-driven at runtime
- Treating extractor runtime support as a major design driver
- Assuming simplification should eliminate dynamic token internals rather than just runtime schema dynamism

## Overall Assessment At End Of Discussion

The simplified direction is considered an improvement over the full detailed spec, but not because it makes the token-overlap problem much easier. It is better because it narrows the runtime model:

- token overlap remains a real built-in subsystem
- scalar units become simple
- build-time metadata remains possible
- runtime no longer needs to behave like a mutable schema engine

The strongest remaining design risk is hidden normalization if repo authoring and runtime representation use the same unit key with different implied `per` semantics.
