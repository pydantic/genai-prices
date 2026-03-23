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


def validate_ancestor_coverage(priced_unit_ids: set[str], family: UnitFamily) -> None:
    """Raise ValueError if any priced unit is missing a priced ancestor.

    Spec Section 8, rule 4: if a model prices a unit, it must also price all ancestors
    of that unit within the same family.
    """
    for unit_id in priced_unit_ids:
        unit = family.units[unit_id]
        for other_id, other in family.units.items():
            if other_id != unit_id and is_descendant_or_self(other, unit) and other_id not in priced_unit_ids:
                raise ValueError(
                    f'Unit {unit_id!r} is priced but its ancestor {other_id!r} is not. '
                    f'All ancestors of a priced unit must also be priced.'
                )


def _get_usage_value(usage: object, key: str) -> int:
    """Get a usage value by key. Supports both Mapping and attribute access. Returns 0 for missing/None."""
    if isinstance(usage, Mapping):
        val: int | None = usage.get(key)  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        return val or 0  # pyright: ignore[reportUnknownVariableType]
    result: int | None = getattr(usage, key, None)
    return result or 0


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

    Precondition: ancestor coverage — if a unit is priced, all its ancestors must
    also be priced. Validated by ModelPrice.__post_init__ (Python) and
    validateAncestorCoverage (JS) at construction/calc time.
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
                f'Negative leaf value ({leaf_value}) for {unit_id}: inconsistent usage values: {", ".join(involved)}'
            )

        result[unit_id] = leaf_value

    return result
