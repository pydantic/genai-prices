from __future__ import annotations

from collections.abc import Collection

from genai_prices.units import UnitDef, UnitRegistry


def validate_price_keys(price_keys: set[str], registry: UnitRegistry) -> None:
    unknown_price_keys = {price_key for price_key in price_keys if _unit_for_price_key(price_key, registry) is None}
    if unknown_price_keys:
        bad_keys = ', '.join(sorted(unknown_price_keys))
        raise ValueError(f'Unknown price key: {bad_keys}')


def validate_ancestor_coverage(priced_usage_keys: set[str], registry: UnitRegistry) -> None:
    for usage_key in sorted(priced_usage_keys):
        missing_ancestors = registry.ancestor_usage_keys(usage_key) - priced_usage_keys
        if missing_ancestors:
            bad_keys = ', '.join(sorted(missing_ancestors))
            raise ValueError(f'Missing ancestor price for {usage_key}: {bad_keys}')


def validate_join_coverage(priced_usage_keys: set[str], registry: UnitRegistry) -> None:
    priced_units = _priced_units(priced_usage_keys, registry)

    _validate_join_coverage_units(priced_units, priced_usage_keys, registry)


def _validate_join_coverage_units(
    priced_units: Collection[UnitDef], priced_usage_keys: set[str], registry: UnitRegistry
) -> None:
    ordered_priced_units = sorted(priced_units, key=lambda unit: unit.usage_key)

    for index, first_unit in enumerate(ordered_priced_units):
        for second_unit in ordered_priced_units[index + 1 :]:
            if not first_unit.is_compatible_with(second_unit):
                continue

            join = registry.find_join(first_unit, second_unit)
            if join is None:
                raise ValueError(
                    f'Missing registered join unit for priced units {first_unit.usage_key} and {second_unit.usage_key}'
                )

            if join.usage_key not in priced_usage_keys:
                raise ValueError(
                    f'Missing join price for {first_unit.usage_key} and {second_unit.usage_key}: {join.usage_key}'
                )


def _priced_units(priced_usage_keys: set[str], registry: UnitRegistry) -> list[UnitDef]:
    return [registry.units[usage_key] for usage_key in sorted(priced_usage_keys)]


def validate_model_price(price_keys: set[str], registry: UnitRegistry) -> None:
    priced_units: list[UnitDef] = []
    unknown_price_keys: set[str] = set()
    for price_key in price_keys:
        unit = _unit_for_price_key(price_key, registry)
        if unit is None:
            unknown_price_keys.add(price_key)
        else:
            priced_units.append(unit)

    if unknown_price_keys:
        bad_keys = ', '.join(sorted(unknown_price_keys))
        raise ValueError(f'Unknown price key: {bad_keys}')

    validate_priced_units(priced_units, registry)


def validate_priced_units(priced_units: Collection[UnitDef], registry: UnitRegistry) -> None:
    """Validate ancestor and join coverage for already-resolved priced units."""
    priced_usage_keys = {unit.usage_key for unit in priced_units}

    validate_ancestor_coverage(priced_usage_keys, registry)
    _validate_join_coverage_units(priced_units, priced_usage_keys, registry)


def validate_extractor_destinations(dest_keys: set[str], reported_usage_keys: set[str] | frozenset[str]) -> None:
    invalid_destinations = dest_keys - reported_usage_keys
    if invalid_destinations:
        bad_keys = ', '.join(sorted(invalid_destinations))
        raise ValueError(f'Invalid extractor destination: {bad_keys}')


def _unit_for_price_key(price_key: str, registry: UnitRegistry) -> UnitDef | None:
    try:
        return registry.unit_for_price_key(price_key)
    except KeyError:
        return None
