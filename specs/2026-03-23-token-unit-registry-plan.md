# Token Unit Registry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded subtraction chain in `calc_price` with a data-driven decomposition engine based on a token unit registry, with no breaking changes.

**Architecture:** New `units.py` defines `UnitFamily`/`UnitDef` types and the token family with 22 units organized by dimensions (direction, modality, cache). New `decompose.py` implements Mobius inversion on the containment poset to compute leaf values, scoped to priced units only. `ModelPrice.calc_price()` is rewired to build a dict from its fixed fields, run decomposition, and price each leaf — producing identical results to the current hardcoded chain.

**Tech Stack:** Python 3.9+, dataclasses, pytest, inline-snapshot

**Spec:** `ignoreme/specs/2026-03-23-unit-registry-spec.md`

---

## Scope

This plan implements **Phase 1** of the unit registry spec: registry infrastructure + data-driven decomposition, keeping the current 7 token unit IDs and ModelPrice fixed fields. No breaking changes to the public API.

**In scope:**

- Unit registry types and token family definition (all 22 units)
- Containment poset and Mobius-inversion decomposition
- Rewiring `ModelPrice.calc_price()` to use decomposition
- All existing tests passing without modification

**Not in scope (Phase 2):**

- Changing `ModelPrice` to dict-based (extensible unit IDs)
- Adding new modality units to YAML schema
- Renaming `cache_audio_read` → `cache_read_audio`
- `AbstractUsage` → `object` type alias
- Ancestor coverage validation rule (needs dict-based ModelPrice)

## Open Questions

1. **Naming: `cache_audio_read` vs `cache_read_audio`** — The spec uses `cache_read_audio_mtok` (consistent: `cache_{operation}_{modality}`) but current code uses `cache_audio_read_mtok`. This plan uses spec-compliant unit IDs in the registry and maps to current field names at the boundary. The rename is deferred to Phase 2.

2. **Behavior improvement for unpriced units** — The current hardcoded chain subtracts audio/cache tokens from the catch-all even when those units are unpriced (the subtracted tokens are then priced at $0, effectively lost). The new decomposition correctly keeps unpriced units' tokens in the catch-all. This is the spec-correct behavior. In practice, no real model has unpriced audio units receiving audio usage, so this shouldn't affect existing tests. If it does, the tests are testing the wrong behavior.

---

## File Structure

**New files:**

- `packages/python/genai_prices/units.py` — Unit types + token family registry
- `packages/python/genai_prices/decompose.py` — Containment + leaf value computation
- `tests/test_units.py` — Registry structure tests
- `tests/test_decompose.py` — Decomposition tests

**Modified files:**

- `packages/python/genai_prices/types.py` — `ModelPrice.calc_price()` rewired (lines 611-659)

---

## Task 1: Unit Registry Types + Token Family

**Files:**

- Create: `packages/python/genai_prices/units.py`
- Test: `tests/test_units.py`

- [ ] **Step 1.1: Write failing tests for unit registry**

```python
# tests/test_units.py
import pytest

from genai_prices.units import TOKENS_FAMILY, UnitDef, UnitFamily, get_family, get_unit


def test_unit_def_creation():
    unit = UnitDef(id='input_mtok', family_id='tokens', usage_key='input_tokens', dimensions={'direction': 'input'})
    assert unit.id == 'input_mtok'
    assert unit.usage_key == 'input_tokens'
    assert unit.dimensions == {'direction': 'input'}


def test_tokens_family_exists():
    family = get_family('tokens')
    assert family.id == 'tokens'
    assert family.per == 1_000_000


def test_get_unit():
    unit = get_unit('input_mtok')
    assert unit.family_id == 'tokens'
    assert unit.usage_key == 'input_tokens'
    assert unit.dimensions == {'direction': 'input'}


def test_get_unit_not_found():
    with pytest.raises(KeyError):
        get_unit('nonexistent')


def test_get_family_not_found():
    with pytest.raises(KeyError):
        get_family('nonexistent')


def test_tokens_family_has_22_units():
    family = get_family('tokens')
    assert len(family.units) == 22


def test_tokens_family_has_all_current_units():
    """All 7 currently-used units exist in the registry."""
    family = get_family('tokens')
    for unit_id in [
        'input_mtok',
        'output_mtok',
        'cache_read_mtok',
        'cache_write_mtok',
        'input_audio_mtok',
        'cache_read_audio_mtok',
        'output_audio_mtok',
    ]:
        assert unit_id in family.units, f'Missing unit: {unit_id}'


def test_tokens_family_has_new_modality_units():
    """All new modality units exist in the registry."""
    family = get_family('tokens')
    for unit_id in [
        'input_text_mtok',
        'output_text_mtok',
        'cache_read_text_mtok',
        'cache_write_text_mtok',
        'input_image_mtok',
        'output_image_mtok',
        'cache_read_image_mtok',
        'cache_write_image_mtok',
        'input_video_mtok',
        'output_video_mtok',
        'cache_read_video_mtok',
        'cache_write_video_mtok',
    ]:
        assert unit_id in family.units, f'Missing unit: {unit_id}'


def test_unit_dimensions_are_valid():
    """Every unit's dimension keys/values must be registered in its family."""
    family = get_family('tokens')
    for unit in family.units.values():
        for dim_key, dim_val in unit.dimensions.items():
            assert dim_key in family.dimensions, f'{unit.id}: unknown dimension key {dim_key}'
            assert dim_val in family.dimensions[dim_key], f'{unit.id}: invalid value {dim_val!r} for {dim_key}'


def test_catch_all_units_have_one_dimension():
    """input_mtok and output_mtok should have only the direction dimension."""
    assert get_unit('input_mtok').dimensions == {'direction': 'input'}
    assert get_unit('output_mtok').dimensions == {'direction': 'output'}


def test_cache_read_audio_usage_key():
    """cache_read_audio_mtok maps to current usage field name (not spec future name)."""
    unit = get_unit('cache_read_audio_mtok')
    assert unit.usage_key == 'cache_audio_read_tokens'
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `uv run pytest tests/test_units.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'genai_prices.units'`

- [ ] **Step 1.3: Implement units.py**

```python
# packages/python/genai_prices/units.py
"""Token unit registry — defines unit families, dimensions, and unit definitions."""

from __future__ import annotations as _annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnitDef:
    """Definition of a single pricing unit."""

    id: str
    family_id: str
    usage_key: str
    dimensions: dict[str, str]


@dataclass(frozen=True)
class UnitFamily:
    """A family of pricing units that share a normalization factor."""

    id: str
    per: int
    description: str
    dimensions: dict[str, list[str]]
    units: dict[str, UnitDef]


def _tok(unit_id: str, usage_key: str, dimensions: dict[str, str]) -> UnitDef:
    return UnitDef(id=unit_id, family_id='tokens', usage_key=usage_key, dimensions=dimensions)


TOKENS_FAMILY = UnitFamily(
    id='tokens',
    per=1_000_000,
    description='Token counts',
    dimensions={
        'direction': ['input', 'output'],
        'modality': ['text', 'audio', 'image', 'video'],
        'cache': ['read', 'write'],
    },
    units={
        # Catch-all input/output (no modality, no cache)
        'input_mtok': _tok('input_mtok', 'input_tokens', {'direction': 'input'}),
        'output_mtok': _tok('output_mtok', 'output_tokens', {'direction': 'output'}),
        # Cache (no modality)
        'cache_read_mtok': _tok('cache_read_mtok', 'cache_read_tokens', {'direction': 'input', 'cache': 'read'}),
        'cache_write_mtok': _tok('cache_write_mtok', 'cache_write_tokens', {'direction': 'input', 'cache': 'write'}),
        # Text modality
        'input_text_mtok': _tok('input_text_mtok', 'input_text_tokens', {'direction': 'input', 'modality': 'text'}),
        'output_text_mtok': _tok('output_text_mtok', 'output_text_tokens', {'direction': 'output', 'modality': 'text'}),
        'cache_read_text_mtok': _tok('cache_read_text_mtok', 'cache_read_text_tokens', {'direction': 'input', 'modality': 'text', 'cache': 'read'}),
        'cache_write_text_mtok': _tok('cache_write_text_mtok', 'cache_write_text_tokens', {'direction': 'input', 'modality': 'text', 'cache': 'write'}),
        # Audio modality
        'input_audio_mtok': _tok('input_audio_mtok', 'input_audio_tokens', {'direction': 'input', 'modality': 'audio'}),
        'output_audio_mtok': _tok('output_audio_mtok', 'output_audio_tokens', {'direction': 'output', 'modality': 'audio'}),
        # NOTE: usage_key uses current field name 'cache_audio_read_tokens', not spec's 'cache_read_audio_tokens'
        'cache_read_audio_mtok': _tok('cache_read_audio_mtok', 'cache_audio_read_tokens', {'direction': 'input', 'modality': 'audio', 'cache': 'read'}),
        'cache_write_audio_mtok': _tok('cache_write_audio_mtok', 'cache_write_audio_tokens', {'direction': 'input', 'modality': 'audio', 'cache': 'write'}),
        # Image modality
        'input_image_mtok': _tok('input_image_mtok', 'input_image_tokens', {'direction': 'input', 'modality': 'image'}),
        'output_image_mtok': _tok('output_image_mtok', 'output_image_tokens', {'direction': 'output', 'modality': 'image'}),
        'cache_read_image_mtok': _tok('cache_read_image_mtok', 'cache_read_image_tokens', {'direction': 'input', 'modality': 'image', 'cache': 'read'}),
        'cache_write_image_mtok': _tok('cache_write_image_mtok', 'cache_write_image_tokens', {'direction': 'input', 'modality': 'image', 'cache': 'write'}),
        # Video modality
        'input_video_mtok': _tok('input_video_mtok', 'input_video_tokens', {'direction': 'input', 'modality': 'video'}),
        'output_video_mtok': _tok('output_video_mtok', 'output_video_tokens', {'direction': 'output', 'modality': 'video'}),
        'cache_read_video_mtok': _tok('cache_read_video_mtok', 'cache_read_video_tokens', {'direction': 'input', 'modality': 'video', 'cache': 'read'}),
        'cache_write_video_mtok': _tok('cache_write_video_mtok', 'cache_write_video_tokens', {'direction': 'input', 'modality': 'video', 'cache': 'write'}),
    },
)

# Mapping from current ModelPrice field names to registry unit IDs.
# Only needed during Phase 1 while ModelPrice uses fixed fields.
FIELD_TO_UNIT: dict[str, str] = {
    'input_mtok': 'input_mtok',
    'output_mtok': 'output_mtok',
    'cache_read_mtok': 'cache_read_mtok',
    'cache_write_mtok': 'cache_write_mtok',
    'input_audio_mtok': 'input_audio_mtok',
    'cache_audio_read_mtok': 'cache_read_audio_mtok',  # field name differs from unit ID
    'output_audio_mtok': 'output_audio_mtok',
}

_FAMILIES: dict[str, UnitFamily] = {'tokens': TOKENS_FAMILY}
_ALL_UNITS: dict[str, UnitDef] = {uid: unit for fam in _FAMILIES.values() for uid, unit in fam.units.items()}


def get_family(family_id: str) -> UnitFamily:
    """Look up a unit family by ID. Raises KeyError if not found."""
    return _FAMILIES[family_id]


def get_unit(unit_id: str) -> UnitDef:
    """Look up a unit definition by ID. Raises KeyError if not found."""
    return _ALL_UNITS[unit_id]
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `uv run pytest tests/test_units.py -v`
Expected: all PASS

- [ ] **Step 1.5: Commit**

```bash
gcap packages/python/genai_prices/units.py tests/test_units.py -m "Add token unit registry types and family definition"
```

---

## Task 2: Containment Helpers

**Files:**

- Create: `packages/python/genai_prices/decompose.py`
- Test: `tests/test_decompose.py`

- [ ] **Step 2.1: Write failing tests for containment**

```python
# tests/test_decompose.py
import pytest

from genai_prices.decompose import get_priced_descendants, is_descendant_or_self
from genai_prices.units import TOKENS_FAMILY, get_unit


class TestContainment:
    def test_self_is_descendant_or_self(self):
        unit = get_unit('input_mtok')
        assert is_descendant_or_self(unit, unit)

    def test_child_is_descendant(self):
        assert is_descendant_or_self(get_unit('input_mtok'), get_unit('cache_read_mtok'))

    def test_parent_is_not_descendant_of_child(self):
        assert not is_descendant_or_self(get_unit('cache_read_mtok'), get_unit('input_mtok'))

    def test_grandchild_is_descendant(self):
        assert is_descendant_or_self(get_unit('input_mtok'), get_unit('cache_read_audio_mtok'))

    def test_lattice_both_parents(self):
        """cache_read_audio is a descendant of both cache_read and input_audio."""
        cra = get_unit('cache_read_audio_mtok')
        assert is_descendant_or_self(get_unit('cache_read_mtok'), cra)
        assert is_descendant_or_self(get_unit('input_audio_mtok'), cra)

    def test_sibling_not_descendant(self):
        assert not is_descendant_or_self(get_unit('cache_read_mtok'), get_unit('cache_write_mtok'))

    def test_different_direction_not_descendant(self):
        assert not is_descendant_or_self(get_unit('input_mtok'), get_unit('output_mtok'))

    def test_wrong_modality_not_descendant(self):
        assert not is_descendant_or_self(get_unit('input_audio_mtok'), get_unit('cache_read_image_mtok'))

    def test_cache_write_not_descendant_of_cache_read(self):
        assert not is_descendant_or_self(get_unit('cache_read_mtok'), get_unit('cache_write_audio_mtok'))


class TestPricedDescendants:
    def test_all_priced(self):
        priced = {'input_mtok', 'cache_read_mtok', 'input_audio_mtok', 'cache_read_audio_mtok'}
        descs = get_priced_descendants('input_mtok', priced, TOKENS_FAMILY)
        assert descs == {'cache_read_mtok', 'input_audio_mtok', 'cache_read_audio_mtok'}

    def test_excludes_unpriced(self):
        priced = {'input_mtok', 'cache_read_mtok'}
        descs = get_priced_descendants('input_mtok', priced, TOKENS_FAMILY)
        assert descs == {'cache_read_mtok'}

    def test_leaf_has_no_descendants(self):
        priced = {'input_mtok', 'cache_read_audio_mtok'}
        descs = get_priced_descendants('cache_read_audio_mtok', priced, TOKENS_FAMILY)
        assert descs == set()

    def test_excludes_self(self):
        priced = {'input_mtok', 'cache_read_mtok'}
        descs = get_priced_descendants('input_mtok', priced, TOKENS_FAMILY)
        assert 'input_mtok' not in descs
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decompose.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'genai_prices.decompose'`

- [ ] **Step 2.3: Implement containment in decompose.py**

```python
# packages/python/genai_prices/decompose.py
"""Decomposition engine — computes leaf values for overlapping usage via Mobius inversion."""

from __future__ import annotations as _annotations

from collections.abc import Mapping

from .units import UnitDef, UnitFamily


def is_descendant_or_self(ancestor: UnitDef, candidate: UnitDef) -> bool:
    """True if candidate's dimensions are a (non-strict) superset of ancestor's within the same family."""
    if ancestor.family_id != candidate.family_id:
        return False
    return all(candidate.dimensions.get(k) == v for k, v in ancestor.dimensions.items())


def get_priced_descendants(unit_id: str, priced_ids: set[str], family: UnitFamily) -> set[str]:
    """Return all priced unit IDs that are strict descendants of the given unit."""
    unit = family.units[unit_id]
    return {uid for uid in priced_ids if uid != unit_id and is_descendant_or_self(unit, family.units[uid])}
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decompose.py -v`
Expected: all PASS

- [ ] **Step 2.5: Commit**

```bash
gcap packages/python/genai_prices/decompose.py tests/test_decompose.py -m "Add containment helpers for unit decomposition"
```

---

## Task 3: Leaf Value Computation

**Files:**

- Modify: `packages/python/genai_prices/decompose.py`
- Modify: `tests/test_decompose.py`

- [ ] **Step 3.1: Write failing tests for leaf value computation**

Add to `tests/test_decompose.py`:

```python
from genai_prices import Usage
from genai_prices.decompose import compute_leaf_values


class TestLeafValues:
    def test_simple_text_model(self):
        """Text-only: no carve-outs."""
        priced = {'input_mtok', 'output_mtok'}
        usage = {'input_tokens': 1000, 'output_tokens': 500}
        assert compute_leaf_values(priced, usage, TOKENS_FAMILY) == {'input_mtok': 1000, 'output_mtok': 500}

    def test_with_cache(self):
        """Cache tokens carved out of input catch-all."""
        priced = {'input_mtok', 'output_mtok', 'cache_read_mtok', 'cache_write_mtok'}
        usage = {'input_tokens': 1000, 'cache_read_tokens': 200, 'cache_write_tokens': 100, 'output_tokens': 500}
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {
            'input_mtok': 700,
            'cache_read_mtok': 200,
            'cache_write_mtok': 100,
            'output_mtok': 500,
        }

    def test_with_audio(self):
        """Audio tokens carved out of input catch-all."""
        priced = {'input_mtok', 'output_mtok', 'input_audio_mtok'}
        usage = {'input_tokens': 1000, 'input_audio_tokens': 300, 'output_tokens': 500}
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {'input_mtok': 700, 'input_audio_mtok': 300, 'output_mtok': 500}

    def test_spec_example(self):
        """Example from Section 4 of the unit registry spec."""
        priced = {'input_mtok', 'cache_read_mtok', 'input_audio_mtok'}
        usage = {'input_tokens': 1000, 'cache_read_tokens': 200, 'input_audio_tokens': 300}
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {'input_mtok': 500, 'cache_read_mtok': 200, 'input_audio_mtok': 300}

    def test_lattice_cache_read_audio(self):
        """cache_read_audio carved from both cache_read and input_audio (lattice structure)."""
        priced = {'input_mtok', 'cache_read_mtok', 'input_audio_mtok', 'cache_read_audio_mtok'}
        usage = {
            'input_tokens': 1000,
            'cache_read_tokens': 200,
            'input_audio_tokens': 300,
            'cache_audio_read_tokens': 50,  # current field name
        }
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {
            'input_mtok': 550,            # 1000 - 200 - 300 + 50
            'cache_read_mtok': 150,       # 200 - 50
            'input_audio_mtok': 250,      # 300 - 50
            'cache_read_audio_mtok': 50,  # leaf
        }

    def test_unpriced_audio_stays_in_catchall(self):
        """If input_audio is NOT priced, audio tokens remain in the catch-all."""
        priced = {'input_mtok', 'output_mtok', 'cache_read_mtok'}
        usage = {
            'input_tokens': 1000,
            'cache_read_tokens': 200,
            'input_audio_tokens': 300,  # not priced — stays in catch-all
            'output_tokens': 500,
        }
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {'input_mtok': 800, 'cache_read_mtok': 200, 'output_mtok': 500}

    def test_missing_usage_is_zero(self):
        """Missing usage values default to zero."""
        priced = {'input_mtok', 'output_mtok', 'cache_read_mtok'}
        usage = {'input_tokens': 1000, 'output_tokens': 500}
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {'input_mtok': 1000, 'cache_read_mtok': 0, 'output_mtok': 500}

    def test_negative_leaf_raises_error(self):
        """Inconsistent usage (cache > input) raises ValueError with helpful message."""
        priced = {'input_mtok', 'cache_read_mtok'}
        usage = {'input_tokens': 100, 'cache_read_tokens': 200}
        with pytest.raises(ValueError, match='input_mtok.*negative|negative.*input_mtok'):
            compute_leaf_values(priced, usage, TOKENS_FAMILY)

    def test_usage_as_object(self):
        """Usage can be an object with attributes (like the Usage dataclass)."""
        priced = {'input_mtok', 'output_mtok', 'cache_read_mtok'}
        usage = Usage(input_tokens=1000, output_tokens=500, cache_read_tokens=200)
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {'input_mtok': 800, 'cache_read_mtok': 200, 'output_mtok': 500}

    def test_full_current_model(self):
        """All 7 current units priced — matches what the hardcoded chain does."""
        priced = {
            'input_mtok',
            'output_mtok',
            'cache_read_mtok',
            'cache_write_mtok',
            'input_audio_mtok',
            'cache_read_audio_mtok',
            'output_audio_mtok',
        }
        usage = {
            'input_tokens': 1000,
            'cache_read_tokens': 200,
            'cache_write_tokens': 100,
            'input_audio_tokens': 300,
            'cache_audio_read_tokens': 50,
            'output_tokens': 800,
            'output_audio_tokens': 150,
        }
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {
            # input_mtok: 1000 - 200 - 100 - 300 + 50 = 450
            'input_mtok': 450,
            'cache_read_mtok': 150,       # 200 - 50
            'cache_write_mtok': 100,      # leaf
            'input_audio_mtok': 250,      # 300 - 50
            'cache_read_audio_mtok': 50,  # leaf
            'output_mtok': 650,           # 800 - 150
            'output_audio_mtok': 150,     # leaf
        }

    def test_output_audio_carved_from_output(self):
        """output_audio carved from output catch-all."""
        priced = {'output_mtok', 'output_audio_mtok'}
        usage = {'output_tokens': 800, 'output_audio_tokens': 200}
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {'output_mtok': 600, 'output_audio_mtok': 200}
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `uv run pytest tests/test_decompose.py::TestLeafValues -v`
Expected: FAIL — `ImportError: cannot import name 'compute_leaf_values'`

- [ ] **Step 3.3: Implement compute_leaf_values**

Add to `packages/python/genai_prices/decompose.py`:

```python
def _get_usage_value(usage: object, key: str) -> int:
    """Get a usage value by key. Supports both Mapping and attribute access. Returns 0 for missing/None."""
    if isinstance(usage, Mapping):
        return usage.get(key) or 0
    return getattr(usage, key, None) or 0


def compute_leaf_values(
    priced_unit_ids: set[str],
    usage: object,
    family: UnitFamily,
) -> dict[str, int]:
    """Compute the leaf value for each priced unit via Mobius inversion on the containment poset.

    Only priced units participate. If a unit is not priced, its usage stays in the
    nearest priced ancestor's catch-all. Raises ValueError on negative leaf values
    (inconsistent usage data).

    The coefficient (-1)^depth_diff is the Mobius function for a product of chains,
    which holds because our dimensions are independent categorical axes. Each step
    in the poset adds exactly one dimension.
    """
    result: dict[str, int] = {}

    for unit_id in priced_unit_ids:
        unit = family.units[unit_id]
        target_depth = len(unit.dimensions)

        # Mobius inversion: sum over all priced descendants (including self)
        # coefficient = (-1)^(depth difference)
        leaf_value = 0
        for other_id in priced_unit_ids:
            other = family.units[other_id]
            if not is_descendant_or_self(unit, other):
                continue
            depth_diff = len(other.dimensions) - target_depth
            coefficient = (-1) ** depth_diff
            leaf_value += coefficient * _get_usage_value(usage, other.usage_key)

        if leaf_value < 0:
            involved = [
                f'{family.units[oid].usage_key}={_get_usage_value(usage, family.units[oid].usage_key)}'
                for oid in priced_unit_ids
                if is_descendant_or_self(unit, family.units[oid])
                and _get_usage_value(usage, family.units[oid].usage_key) != 0
            ]
            raise ValueError(
                f'Negative leaf value ({leaf_value}) for {unit_id}: '
                f'inconsistent usage values: {", ".join(involved)}'
            )

        result[unit_id] = leaf_value

    return result
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `uv run pytest tests/test_decompose.py -v`
Expected: all PASS

- [ ] **Step 3.5: Commit**

```bash
gcap packages/python/genai_prices/decompose.py tests/test_decompose.py -m "Add leaf value computation via Mobius inversion"
```

---

## Task 4: Rewire ModelPrice.calc_price

Replace the hardcoded subtraction chain (lines 611-659 of `types.py`) with registry-driven decomposition. The public API and behavior are unchanged.

**Files:**

- Modify: `packages/python/genai_prices/types.py:611-659`

**Important context for implementer:**

- The current hardcoded chain at `types.py:611-659` manually subtracts audio tokens from text, cache from input, etc. The new code builds a dict of `{unit_id: price}` from ModelPrice's fixed fields, runs `compute_leaf_values`, then prices each leaf.
- `calc_mtok_price()` (line 678) is preserved — it handles both flat `Decimal` and `TieredPrices`.
- `requests_kcount` is not a token unit; it stays as a special case at the end.
- Direction is determined from unit dimensions: `direction: input` → `input_price`, `direction: output` → `output_price`.

- [ ] **Step 4.1: Write equivalence tests**

Add to `tests/test_decompose.py`:

```python
from decimal import Decimal

from genai_prices import Usage
from genai_prices.types import ModelPrice


class TestCalcPriceEquivalence:
    """Verify the rewired calc_price produces the same results as the hardcoded chain."""

    def test_simple_text(self):
        mp = ModelPrice(input_mtok=Decimal('3'), output_mtok=Decimal('15'))
        result = mp.calc_price(Usage(input_tokens=1_000_000, output_tokens=500_000))
        assert result['input_price'] == Decimal('3')
        assert result['output_price'] == Decimal('7.5')
        assert result['total_price'] == Decimal('10.5')

    def test_with_cache(self):
        mp = ModelPrice(
            input_mtok=Decimal('3'),
            output_mtok=Decimal('15'),
            cache_read_mtok=Decimal('0.3'),
            cache_write_mtok=Decimal('3.75'),
        )
        usage = Usage(input_tokens=1000, cache_read_tokens=200, cache_write_tokens=100, output_tokens=500)
        result = mp.calc_price(usage)
        # input leaf: 1000 - 200 - 100 = 700
        expected_input = (Decimal('3') * 700 + Decimal('0.3') * 200 + Decimal('3.75') * 100) / 1_000_000
        assert result['input_price'] == expected_input

    def test_with_audio_and_cache(self):
        """All 7 current units priced, with audio and cache."""
        mp = ModelPrice(
            input_mtok=Decimal('5'),
            output_mtok=Decimal('20'),
            cache_read_mtok=Decimal('0.5'),
            cache_write_mtok=Decimal('6.25'),
            input_audio_mtok=Decimal('100'),
            output_audio_mtok=Decimal('200'),
            cache_audio_read_mtok=Decimal('2.5'),
        )
        usage = Usage(
            input_tokens=1000,
            cache_read_tokens=200,
            cache_write_tokens=100,
            input_audio_tokens=300,
            cache_audio_read_tokens=50,
            output_tokens=800,
            output_audio_tokens=150,
        )
        result = mp.calc_price(usage)
        # Leaf values (see test_full_current_model in TestLeafValues):
        # input_mtok: 450, cache_read: 150, cache_write: 100
        # input_audio: 250, cache_read_audio: 50
        # output: 650, output_audio: 150
        expected_input = (
            Decimal('5') * 450
            + Decimal('0.5') * 150
            + Decimal('6.25') * 100
            + Decimal('100') * 250
            + Decimal('2.5') * 50
        ) / 1_000_000
        expected_output = (Decimal('20') * 650 + Decimal('200') * 150) / 1_000_000
        assert result['input_price'] == expected_input
        assert result['output_price'] == expected_output

    def test_with_tiered_prices(self):
        """TieredPrices still works through the new decomposition path."""
        from genai_prices.types import TieredPrices, Tier

        mp = ModelPrice(
            input_mtok=TieredPrices(base=Decimal('3'), tiers=[Tier(start=200_000, price=Decimal('6'))]),
            output_mtok=TieredPrices(base=Decimal('15'), tiers=[Tier(start=200_000, price=Decimal('30'))]),
            cache_read_mtok=Decimal('0.3'),
        )
        # Below threshold
        usage_low = Usage(input_tokens=100_000, cache_read_tokens=20_000, output_tokens=50_000)
        result_low = mp.calc_price(usage_low)
        expected_input_low = (Decimal('3') * 80_000 + Decimal('0.3') * 20_000) / 1_000_000
        expected_output_low = Decimal('15') * 50_000 / 1_000_000
        assert result_low['input_price'] == expected_input_low
        assert result_low['output_price'] == expected_output_low

        # Above threshold — tier applies to ALL tokens of that type
        usage_high = Usage(input_tokens=300_000, cache_read_tokens=50_000, output_tokens=100_000)
        result_high = mp.calc_price(usage_high)
        expected_input_high = (Decimal('6') * 250_000 + Decimal('0.3') * 50_000) / 1_000_000
        expected_output_high = Decimal('30') * 100_000 / 1_000_000
        assert result_high['input_price'] == expected_input_high
        assert result_high['output_price'] == expected_output_high

    def test_with_requests(self):
        mp = ModelPrice(input_mtok=Decimal('3'), output_mtok=Decimal('15'), requests_kcount=Decimal('1'))
        result = mp.calc_price(Usage(input_tokens=1000, output_tokens=500))
        expected = Decimal('3') * 1000 / 1_000_000 + Decimal('15') * 500 / 1_000_000 + Decimal('1') / 1000
        assert result['total_price'] == expected

    def test_none_usage(self):
        mp = ModelPrice(input_mtok=Decimal('3'), output_mtok=Decimal('15'))
        result = mp.calc_price(Usage())
        assert result['total_price'] == Decimal('0')
```

- [ ] **Step 4.2: Run equivalence tests (they use the OLD calc_price)**

Run: `uv run pytest tests/test_decompose.py::TestCalcPriceEquivalence -v`
Expected: PASS (validating our expected values against the current implementation)

- [ ] **Step 4.3: Rewrite `ModelPrice.calc_price`**

Replace `types.py` lines 611-659 with:

```python
    def calc_price(self, usage: AbstractUsage) -> CalcPrice:
        """Calculate the price of usage in USD with this model price."""
        # NOTE: If these imports cause circular import issues, move them inside
        # the method body. Test by running `python -c "from genai_prices import calc_price"`.
        from .decompose import compute_leaf_values
        from .units import FIELD_TO_UNIT, TOKENS_FAMILY, get_unit

        # Build priced units dict from fixed fields
        priced: dict[str, Decimal | TieredPrices] = {}
        for field_name, unit_id in FIELD_TO_UNIT.items():
            price = getattr(self, field_name)
            if price is not None:
                priced[unit_id] = price

        # Total input tokens for tier determination (before decomposition)
        total_input_tokens = getattr(usage, 'input_tokens', None) or 0

        # Compute leaf values via decomposition
        leaf_values = compute_leaf_values(set(priced.keys()), usage, TOKENS_FAMILY)

        # Price each unit and bucket by direction
        input_price = Decimal(0)
        output_price = Decimal(0)
        for unit_id, leaf_count in leaf_values.items():
            unit = get_unit(unit_id)
            cost = calc_mtok_price(priced[unit_id], leaf_count, total_input_tokens)
            if unit.dimensions.get('direction') == 'input':
                input_price += cost
            else:
                output_price += cost

        total_price = input_price + output_price

        if self.requests_kcount is not None:
            total_price += self.requests_kcount / 1000

        return {'input_price': input_price, 'output_price': output_price, 'total_price': total_price}
```

- [ ] **Step 4.4: Run equivalence tests to verify they still pass**

Run: `uv run pytest tests/test_decompose.py::TestCalcPriceEquivalence -v`
Expected: PASS

- [ ] **Step 4.5: Run the FULL existing test suite**

Run: `make test`
Expected: ALL PASS

If any test fails, check whether it's the behavior improvement described in Open Question 2 (unpriced audio units). If so, the new behavior is correct — update the test's expected values. If not, investigate the decomposition.

- [ ] **Step 4.6: Commit**

```bash
gcap packages/python/genai_prices/types.py -m "Rewire calc_price to use registry-driven decomposition

Replaces the hardcoded subtraction chain with Mobius inversion over
the token unit containment poset. Produces identical results for all
current models. Only priced units participate in decomposition."
```

---

## Verification Checklist

After all tasks are complete:

- [ ] `make test` — all tests pass
- [ ] `make typecheck` — no new type errors
- [ ] `make lint` — clean
- [ ] `make build` — data.json builds successfully
- [ ] No changes to `data.json`, `data_slim.json`, or `data.py` (behavior-preserving refactor)
- [ ] Public API unchanged: `calc_price`, `Usage`, `AbstractUsage`, `ModelPrice` all work as before
