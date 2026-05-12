from __future__ import annotations

import re
from collections.abc import Mapping
from itertools import combinations
from typing import Any, cast

from genai_prices.units import UnitDef, UnitFamily, UnitRegistry

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


def validate_unit_families(unit_families: Mapping[str, Mapping[str, Any]]) -> UnitRegistry:
    """Validate publishable unit-family data and return the indexed registry."""
    usage_keys: set[str] = set()
    price_keys: set[str] = set()

    for family_id, raw_family in unit_families.items():
        dimension_sets: dict[frozenset[tuple[str, str]], str] = {}
        raw_units = cast(Mapping[str, Mapping[str, Any]], raw_family.get('units', {}))
        for usage_key, raw_unit in raw_units.items():
            _validate_public_key('usage', usage_key)
            if usage_key in usage_keys:
                raise ValueError(f'Duplicate unit usage key: {usage_key}')
            usage_keys.add(usage_key)

            price_key = cast(str, raw_unit.get('price_key', usage_key))
            _validate_public_key('price', price_key)
            if price_key in price_keys:
                raise ValueError(f'Duplicate unit price key: {price_key}')
            price_keys.add(price_key)

            dimension_set = frozenset(cast(Mapping[str, str], raw_unit.get('dimensions', {})).items())
            if existing_usage_key := dimension_sets.get(dimension_set):
                raise ValueError(
                    f'Duplicate dimensions in unit family {family_id}: {existing_usage_key} and {usage_key}'
                )
            dimension_sets[dimension_set] = usage_key

    registry = UnitRegistry(unit_families)
    _validate_interval_closure(registry)
    return registry


def validate_export_payload(providers: list[Provider], unit_families: Mapping[str, Mapping[str, Any]]) -> UnitRegistry:
    """Validate registry structure, provider model prices, and extractor destinations before export."""
    from prices.package_data import validate_provider_extractor_destinations, validate_provider_model_prices

    registry = validate_unit_families(unit_families)
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
    for family in registry.families.values():
        _validate_family_interval_closure(family)


def _validate_family_interval_closure(family: UnitFamily) -> None:
    for ancestor in family.units.values():
        for descendant in family.units.values():
            if ancestor is descendant or not _is_dimension_subset(ancestor, descendant):
                continue

            added_dimensions = descendant.dimensions.items() - ancestor.dimensions.items()
            for size in range(1, len(added_dimensions)):
                for added_subset in combinations(added_dimensions, size):
                    required_dimensions = frozenset(ancestor.dimensions.items() | set(added_subset))
                    if required_dimensions in family.units_by_dimension:
                        continue

                    missing_dimensions = ', '.join(f'{key}={value}' for key, value in sorted(required_dimensions))
                    raise ValueError(
                        f'Missing intermediate unit dimensions in family {family.id} '
                        f'between {ancestor.usage_key} and {descendant.usage_key}: '
                        f'{missing_dimensions}'
                    )


def _is_dimension_subset(maybe_ancestor: UnitDef, unit: UnitDef) -> bool:
    return maybe_ancestor.dimensions.items() <= unit.dimensions.items()
