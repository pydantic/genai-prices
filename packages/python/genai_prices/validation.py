from __future__ import annotations

from genai_prices.units import UnitDef, UnitFamily, UnitRegistry


def validate_price_keys(price_keys: set[str], registry: UnitRegistry) -> None:
    unknown_price_keys = {price_key for price_key in price_keys if _unit_for_price_key(price_key, registry) is None}
    if unknown_price_keys:
        bad_keys = ', '.join(sorted(unknown_price_keys))
        raise ValueError(f'Unknown price key: {bad_keys}')


def validate_ancestor_coverage(priced_usage_keys: set[str], family: UnitFamily, registry: UnitRegistry) -> None:
    family_priced_usage_keys = priced_usage_keys & family.units.keys()
    for usage_key in sorted(family_priced_usage_keys):
        missing_ancestors = registry.ancestor_usage_keys(usage_key) - family_priced_usage_keys
        if missing_ancestors:
            bad_keys = ', '.join(sorted(missing_ancestors))
            raise ValueError(f'Missing ancestor price for {usage_key}: {bad_keys}')


def validate_join_coverage(priced_usage_keys: set[str], family: UnitFamily) -> None:
    family_priced_usage_keys = priced_usage_keys & family.units.keys()
    priced_units = _priced_units(family_priced_usage_keys, family)

    for index, first_unit in enumerate(priced_units):
        for second_unit in priced_units[index + 1 :]:
            if not first_unit.is_compatible_with(second_unit):
                continue

            join = family.find_join(first_unit, second_unit)
            if join is None:
                raise ValueError(
                    f'Missing registered join unit for priced units {first_unit.usage_key} and {second_unit.usage_key}'
                )

            if join.usage_key not in family_priced_usage_keys:
                raise ValueError(
                    f'Missing join price for {first_unit.usage_key} and {second_unit.usage_key}: {join.usage_key}'
                )


def _priced_units(priced_usage_keys: set[str], family: UnitFamily) -> list[UnitDef]:
    return [family.units[usage_key] for usage_key in sorted(priced_usage_keys)]


def validate_model_price(price_keys: set[str], registry: UnitRegistry) -> None:
    validate_price_keys(price_keys, registry)

    usage_keys_by_family: dict[UnitFamily, set[str]] = {}
    for price_key in price_keys:
        unit = registry.unit_for_price_key(price_key)
        usage_keys_by_family.setdefault(unit.family, set()).add(unit.usage_key)

    for family, priced_usage_keys in usage_keys_by_family.items():
        validate_ancestor_coverage(priced_usage_keys, family, registry)
        validate_join_coverage(priced_usage_keys, family)


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
