from __future__ import annotations

import keyword
import re
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations
from types import MappingProxyType
from typing import Any, cast

_RESERVED_PUBLIC_KEYS = frozenset({'__proto__', 'constructor', 'prototype'})
_PUBLIC_KEY_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')
_JAVASCRIPT_KEYWORDS = frozenset(
    {
        'arguments',
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
        'eval',
        'export',
        'extends',
        'false',
        'finally',
        'for',
        'function',
        'if',
        'implements',
        'import',
        'in',
        'instanceof',
        'interface',
        'let',
        'new',
        'null',
        'package',
        'private',
        'protected',
        'public',
        'return',
        'static',
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
_RESERVED_KEYWORDS = frozenset(keyword.kwlist) | _JAVASCRIPT_KEYWORDS


@dataclass
class UnitDef:
    usage_key: str
    price_key: str
    per: int
    dimensions: dict[str, str]

    def is_compatible_with(self, other: UnitDef) -> bool:
        """Return whether two units can overlap without conflicting dimensions."""
        return all(other.dimensions.get(key, value) == value for key, value in self.dimensions.items())


class UnitRegistry:
    units: Mapping[str, UnitDef]
    _all_usage_keys: frozenset[str]
    _all_price_keys: frozenset[str]
    _reported_usage_keys: frozenset[str]
    _reported_usage_keys_in_order: tuple[str, ...]
    _units_by_price_key: dict[str, UnitDef]
    _units_by_dimension: dict[frozenset[tuple[str, str]], UnitDef]
    _ancestor_usage_keys: dict[str, frozenset[str]]

    def __init__(self, raw_units: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        """Parse raw unit dictionaries into indexed runtime objects."""
        units: dict[str, UnitDef] = {}
        self._units_by_price_key = {}
        self._units_by_dimension = {}
        self._ancestor_usage_keys = {}

        for usage_key, raw_unit in (raw_units or {}).items():
            dimensions = dict(cast(Mapping[str, str], raw_unit.get('dimensions', {})))
            unit = UnitDef(
                usage_key=usage_key,
                price_key=cast(str, raw_unit.get('price_key', usage_key)),
                per=cast(int, raw_unit['per']),
                dimensions=dimensions,
            )

            dimension_set = _dimension_set(unit)

            units[usage_key] = unit
            self._units_by_price_key[unit.price_key] = unit
            self._units_by_dimension[dimension_set] = unit

        for usage_key, unit in units.items():
            self._ancestor_usage_keys[usage_key] = frozenset(
                maybe_ancestor.usage_key
                for maybe_ancestor in units.values()
                if maybe_ancestor is not unit and _is_dimension_subset(maybe_ancestor, unit)
            )

        self.units = MappingProxyType(units)
        self._all_usage_keys = frozenset(units)
        self._all_price_keys = frozenset(self._units_by_price_key)
        self._reported_usage_keys_in_order = tuple(usage_key for usage_key in units if usage_key != 'requests')
        self._reported_usage_keys = frozenset(self._reported_usage_keys_in_order)

    @classmethod
    def from_untrusted(cls, raw_units: object) -> UnitRegistry:
        """Validate untrusted runtime unit definitions before indexing them."""
        units = _validate_raw_units(raw_units)
        registry = cls(units)
        _validate_interval_closure(registry, _infer_dimension_requirements(registry))
        _validate_join_closedness(registry)
        return registry

    def unit_for_price_key(self, price_key: str) -> UnitDef:
        """Return the registered unit priced by price_key."""
        return self._units_by_price_key[price_key]

    def ancestor_usage_keys(self, usage_key: str) -> frozenset[str]:
        return self._ancestor_usage_keys[usage_key]

    def find_join(self, a: UnitDef, b: UnitDef) -> UnitDef | None:
        """Return the most specific registered unit joining two compatible units, if present."""
        if not a.is_compatible_with(b):
            return None

        return self._units_by_dimension.get(frozenset(a.dimensions.items() | b.dimensions.items()))


def _dimension_set(unit: UnitDef) -> frozenset[tuple[str, str]]:
    return frozenset(unit.dimensions.items())


def _is_dimension_subset(maybe_ancestor: UnitDef, unit: UnitDef) -> bool:
    return maybe_ancestor.dimensions.items() <= unit.dimensions.items()


def _validate_raw_units(raw_units: object) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_units, Mapping):
        raise ValueError('Unit definitions must be an object')

    units: dict[str, dict[str, Any]] = {}
    price_keys: set[str] = set()
    per_by_family: dict[str, int] = {}
    dimension_sets: dict[frozenset[tuple[str, str]], str] = {}
    raw_units_mapping = cast(Mapping[object, object], raw_units)
    for raw_usage_key, raw_unit_value in raw_units_mapping.items():
        if not isinstance(raw_usage_key, str):
            raise ValueError('Unit usage keys must be strings')
        usage_key = raw_usage_key
        _validate_public_key('usage', usage_key)
        if not isinstance(raw_unit_value, Mapping):
            raise ValueError(f'Unit definition for {usage_key} must be an object')
        raw_unit = cast(Mapping[object, object], raw_unit_value)
        if not all(isinstance(key, str) for key in raw_unit):
            raise ValueError(f'Unit definition fields for {usage_key} must be strings')
        unit = cast(Mapping[str, object], raw_unit)

        unknown_fields = unit.keys() - {'per', 'price_key', 'dimensions'}
        if unknown_fields:
            bad_fields = ', '.join(sorted(unknown_fields))
            raise ValueError(f'Unknown unit definition fields for {usage_key}: {bad_fields}')

        price_key_value = unit.get('price_key', usage_key)
        if not isinstance(price_key_value, str):
            raise ValueError(f'Unit price key for {usage_key} must be a string')
        price_key = price_key_value
        _validate_public_key('price', price_key)
        if price_key in price_keys:
            raise ValueError(f'Duplicate unit price key: {price_key}')
        price_keys.add(price_key)

        per_value = unit.get('per')
        if not isinstance(per_value, int) or isinstance(per_value, bool) or per_value <= 0:
            raise ValueError(f'Unit per for {usage_key} must be a positive integer')
        per = per_value

        dimensions_value = unit.get('dimensions')
        if not isinstance(dimensions_value, Mapping):
            raise ValueError(f'Unit dimensions for {usage_key} must be an object')
        raw_dimensions = cast(Mapping[object, object], dimensions_value)
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in raw_dimensions.items()):
            raise ValueError(f'Unit dimensions for {usage_key} must map strings to strings')
        dimensions = dict(cast(Mapping[str, str], raw_dimensions))
        family_value = dimensions.get('family')
        if family_value is None:
            raise ValueError(f'Missing required family dimension for unit {usage_key}')

        existing_per = per_by_family.setdefault(family_value, per)
        if existing_per != per:
            raise ValueError(
                f'Inconsistent per for family dimension {family_value}: expected {existing_per}, got {per} on {usage_key}'
            )

        dimension_set = frozenset(dimensions.items())
        if existing_usage_key := dimension_sets.get(dimension_set):
            raise ValueError(f'Duplicate unit dimensions: {existing_usage_key} and {usage_key}')
        dimension_sets[dimension_set] = usage_key

        normalized: dict[str, Any] = {'per': per, 'dimensions': dimensions}
        if price_key != usage_key:
            normalized['price_key'] = price_key
        units[usage_key] = normalized

    return units


def _validate_public_key(kind: str, key: str) -> None:
    if key.startswith('_'):
        raise ValueError(f'Invalid unit {kind} key: {key!r} must not start with "_"')
    if not _PUBLIC_KEY_PATTERN.fullmatch(key):
        raise ValueError(f'Invalid unit {kind} key: {key!r} is not a public identifier')
    if key in _RESERVED_KEYWORDS:
        raise ValueError(f'Invalid unit {kind} key: {key!r} is a reserved keyword')
    if key in _RESERVED_PUBLIC_KEYS:
        raise ValueError(f'Invalid unit {kind} key: {key!r} is reserved')


def _infer_dimension_requirements(
    registry: UnitRegistry,
) -> dict[tuple[str, str], frozenset[tuple[str, str]]]:
    occurrences: dict[tuple[str, str], list[frozenset[tuple[str, str]]]] = {}
    for unit in registry.units.values():
        dimension_set = frozenset(unit.dimensions.items())
        for dimension in dimension_set:
            occurrences.setdefault(dimension, []).append(dimension_set)

    requirements: dict[tuple[str, str], frozenset[tuple[str, str]]] = {}
    for dimension, dimension_sets in occurrences.items():
        common_dimensions = dimension_sets[0]
        for dimension_set in dimension_sets[1:]:
            common_dimensions &= dimension_set
        requirements[dimension] = common_dimensions - {dimension}
    return requirements


def _validate_interval_closure(
    registry: UnitRegistry,
    requirements: Mapping[tuple[str, str], frozenset[tuple[str, str]]],
) -> None:
    for ancestor in registry.units.values():
        for descendant in registry.units.values():
            if ancestor is descendant or not _is_dimension_subset(ancestor, descendant):
                continue

            ancestor_dimensions = _dimension_set(ancestor)
            descendant_dimensions = _dimension_set(descendant)
            for added_dimension in descendant_dimensions - ancestor_dimensions:
                required_dimensions = _requirement_closure(
                    ancestor_dimensions | {added_dimension},
                    requirements,
                )
                if required_dimensions == descendant_dimensions:
                    continue
                if required_dimensions in registry._units_by_dimension:  # pyright: ignore[reportPrivateUsage]
                    continue

                missing_dimensions = ', '.join(f'{key}={value}' for key, value in sorted(required_dimensions))
                raise ValueError(
                    f'Missing intermediate unit dimensions between {ancestor.usage_key} and '
                    f'{descendant.usage_key}: {missing_dimensions}'
                )


def _requirement_closure(
    dimensions: frozenset[tuple[str, str]],
    requirements: Mapping[tuple[str, str], frozenset[tuple[str, str]]],
) -> frozenset[tuple[str, str]]:
    closed_dimensions = set(dimensions)
    pending_dimensions = list(dimensions)
    while pending_dimensions:
        dimension = pending_dimensions.pop()
        for requirement in requirements[dimension] - closed_dimensions:
            closed_dimensions.add(requirement)
            pending_dimensions.append(requirement)
    return frozenset(closed_dimensions)


def _validate_join_closedness(registry: UnitRegistry) -> None:
    for first, second in combinations(registry.units.values(), 2):
        if not first.is_compatible_with(second):
            continue

        required_dimensions = frozenset(first.dimensions.items() | second.dimensions.items())
        if required_dimensions in registry._units_by_dimension:  # pyright: ignore[reportPrivateUsage]
            continue

        missing_dimensions = ', '.join(f'{key}={value}' for key, value in sorted(required_dimensions))
        raise ValueError(
            f'Missing join unit dimensions between {first.usage_key} and {second.usage_key}: {missing_dimensions}'
        )


def _get_registry() -> UnitRegistry:  # pyright: ignore[reportUnusedFunction]
    from genai_prices.runtime_state import get_runtime_registry

    return get_runtime_registry()
