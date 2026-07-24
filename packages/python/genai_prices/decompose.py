from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from genai_prices.units import UnitDef


def is_descendant_or_self(ancestor: UnitDef, descendant: UnitDef) -> bool:
    return ancestor.dimensions.items() <= descendant.dimensions.items()


def compute_leaf_values(
    priced_usage_keys: set[str], usage: object, units_by_usage_key: Mapping[str, UnitDef]
) -> dict[str, int]:
    priced_units = sorted(
        (units_by_usage_key[usage_key] for usage_key in priced_usage_keys & units_by_usage_key.keys()),
        key=lambda unit: (-len(unit.dimensions), unit.usage_key),
    )
    leaf_values: dict[str, int] = {}

    for unit in priced_units:
        leaf_value = _usage_value(usage, unit.usage_key)
        for descendant in priced_units:
            if descendant is unit or not is_descendant_or_self(unit, descendant):
                continue
            leaf_value -= leaf_values[descendant.usage_key]

        if leaf_value < 0:
            raise ValueError(_negative_leaf_error_message(unit, priced_units, usage, leaf_value))

        leaf_values[unit.usage_key] = leaf_value

    return leaf_values


def _usage_value(usage: object, usage_key: str) -> int:
    raw_value = getattr(usage, usage_key, None)
    return 0 if raw_value is None else cast(int, raw_value)


def _negative_leaf_error_message(unit: UnitDef, priced_units: list[UnitDef], usage: object, leaf_value: int) -> str:
    unit_value = _usage_value(usage, unit.usage_key)
    descendant_values = [
        (descendant, value)
        for descendant in priced_units
        if descendant is not unit
        and is_descendant_or_self(unit, descendant)
        and (value := _usage_value(usage, descendant.usage_key)) > 0
    ]

    for descendant, value in descendant_values:
        if value > unit_value:
            return f'Invalid usage data: {descendant.usage_key} ({value}) cannot exceed {unit.usage_key} ({unit_value})'

    descendant_keys = ', '.join(descendant.usage_key for descendant, _ in descendant_values)
    descendant_total = unit_value - leaf_value
    return (
        f'Invalid usage data: more-specific usage for {descendant_keys} totals {descendant_total}, '
        f'which exceeds {unit.usage_key} ({unit_value})'
    )
