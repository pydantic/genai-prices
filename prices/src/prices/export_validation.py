from __future__ import annotations

import re
from collections.abc import Mapping
from itertools import combinations
from typing import Any, cast

from genai_prices.units import UnitDef, UnitRegistry

from .prices_types import Provider

_RESERVED_PUBLIC_KEYS = frozenset({'__proto__', 'constructor', 'prototype'})
_PUBLIC_KEY_PATTERN = re.compile(r'^[A-Za-z_$][A-Za-z0-9_$]*$')
_RESERVED_KEYWORDS = frozenset(
    {
        'await',
        'break',
        'case',
        'catch',
        'class',
        'const',
        'continue',
        'debugger',
        'default',
        'delete',
        'do',
        'else',
        'enum',
        'export',
        'extends',
        'false',
        'finally',
        'for',
        'function',
        'if',
        'import',
        'in',
        'instanceof',
        'new',
        'null',
        'return',
        'super',
        'switch',
        'this',
        'throw',
        'true',
        'try',
        'typeof',
        'var',
        'void',
        'while',
        'with',
        'yield',
    }
)


def validate_units(raw_units: Mapping[str, Mapping[str, Any]]) -> UnitRegistry:
    """Validate publishable flat unit data and return the indexed registry."""
    price_keys: set[str] = set()
    per_by_family: dict[str, int] = {}
    dimension_sets_by_family: dict[str, dict[frozenset[tuple[str, str]], str]] = {}

    for usage_key, raw_unit in raw_units.items():
        _validate_public_key('usage', usage_key)

        price_key = cast(str, raw_unit.get('price_key', usage_key))
        _validate_public_key('price', price_key)
        if price_key in price_keys:
            raise ValueError(f'Duplicate unit price key: {price_key}')
        price_keys.add(price_key)

        if 'per' not in raw_unit:
            raise ValueError(f'Missing per for unit {usage_key}')
        per = cast(int, raw_unit['per'])

        dimensions = dict(cast(Mapping[str, str], raw_unit.get('dimensions', {})))
        family_value = dimensions.get('family')
        if family_value is None:
            raise ValueError(f'Missing required family dimension for unit {usage_key}')

        existing_per = per_by_family.setdefault(family_value, per)
        if existing_per != per:
            raise ValueError(
                f'Inconsistent per for family dimension {family_value}: expected {existing_per}, got {per} on {usage_key}'
            )

        dimension_set = frozenset(dimensions.items())
        dimension_sets = dimension_sets_by_family.setdefault(family_value, {})
        if existing_usage_key := dimension_sets.get(dimension_set):
            raise ValueError(
                f'Duplicate dimensions in family dimension {family_value}: {existing_usage_key} and {usage_key}'
            )
        dimension_sets[dimension_set] = usage_key

    registry = UnitRegistry(raw_units)
    _validate_interval_closure(registry)
    return registry


def validate_export_payload(providers: list[Provider], units: Mapping[str, Mapping[str, Any]]) -> UnitRegistry:
    """Validate registry structure, provider model prices, and extractor destinations before export."""
    from prices.package_data import validate_provider_extractor_destinations, validate_provider_model_prices

    registry = validate_units(units)
    validate_provider_model_prices(providers, registry)
    validate_provider_extractor_destinations(providers, registry)
    return registry


def _validate_public_key(kind: str, key: str) -> None:
    if not _PUBLIC_KEY_PATTERN.fullmatch(key):
        raise ValueError(f'Invalid unit {kind} key: {key!r} is not a public identifier')
    if key in _RESERVED_KEYWORDS:
        raise ValueError(f'Invalid unit {kind} key: {key!r} is a reserved keyword')
    if key.startswith('_'):
        raise ValueError(f'Invalid unit {kind} key: {key!r} must not start with "_"')
    if key in _RESERVED_PUBLIC_KEYS:
        raise ValueError(f'Invalid unit {kind} key: {key!r} is reserved')


def _validate_interval_closure(registry: UnitRegistry) -> None:
    for family_value in registry.family_values():
        _validate_family_interval_closure(family_value, registry)


def _validate_family_interval_closure(family_value: str, registry: UnitRegistry) -> None:
    units = registry.units_for_family(family_value)
    units_by_dimension = registry._units_by_dimension_by_family[family_value]  # pyright: ignore[reportPrivateUsage]
    for ancestor in units.values():
        for descendant in units.values():
            if ancestor is descendant or not _is_dimension_subset(ancestor, descendant):
                continue

            added_dimensions = descendant.dimensions.items() - ancestor.dimensions.items()
            for size in range(1, len(added_dimensions)):
                for added_subset in combinations(added_dimensions, size):
                    required_dimensions = frozenset(ancestor.dimensions.items() | set(added_subset))
                    if required_dimensions in units_by_dimension:
                        continue

                    missing_dimensions = ', '.join(f'{key}={value}' for key, value in sorted(required_dimensions))
                    raise ValueError(
                        f'Missing intermediate unit dimensions in family dimension {family_value} '
                        f'between {ancestor.usage_key} and {descendant.usage_key}: '
                        f'{missing_dimensions}'
                    )


def _is_dimension_subset(maybe_ancestor: UnitDef, unit: UnitDef) -> bool:
    return maybe_ancestor.dimensions.items() <= unit.dimensions.items()
