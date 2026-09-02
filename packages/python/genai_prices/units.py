from __future__ import annotations

import keyword
import re
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations
from types import MappingProxyType
from typing import Any, cast

_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_MAX_UNIT_COUNT = 4096
_PUBLIC_KEY_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')
_RESERVED_PUBLIC_KEYS = frozenset({'__proto__', 'constructor', 'prototype'})
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


@dataclass(frozen=True)
class UnitDef:
    usage_key: str
    price_key: str
    per: int
    dimensions: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'dimensions', MappingProxyType(dict(self.dimensions)))

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

        units_by_family: dict[str, list[UnitDef]] = {}
        for unit in units.values():
            units_by_family.setdefault(unit.dimensions['family'], []).append(unit)
        for usage_key, unit in units.items():
            self._ancestor_usage_keys[usage_key] = frozenset(
                maybe_ancestor.usage_key
                for maybe_ancestor in units_by_family[unit.dimensions['family']]
                if maybe_ancestor is not unit and _is_dimension_subset(maybe_ancestor, unit)
            )

        self.units = MappingProxyType(units)
        self._all_usage_keys = frozenset(units)
        self._all_price_keys = frozenset(self._units_by_price_key)
        self._reported_usage_keys_in_order = tuple(usage_key for usage_key in units if usage_key != 'requests')
        self._reported_usage_keys = frozenset(self._reported_usage_keys_in_order)

    @classmethod
    def _from_untrusted(cls, raw_units: object) -> UnitRegistry:
        """Validate and construct the understood projection of decoded v3 unit data."""
        raw_units_mapping = _object_mapping(raw_units, 'Invalid units: expected an object')
        if len(raw_units_mapping) > _MAX_UNIT_COUNT:
            raise ValueError(f'Invalid units: expected at most {_MAX_UNIT_COUNT} entries')
        canonical_units: dict[str, dict[str, Any]] = {}
        usage_key_by_price_key: dict[str, str] = {}
        usage_key_by_dimensions: dict[frozenset[tuple[str, str]], str] = {}
        per_by_family: dict[str, int] = {}

        for raw_usage_key, raw_unit in raw_units_mapping.items():
            if not isinstance(raw_usage_key, str):
                raise ValueError(f'Invalid unit usage key: {raw_usage_key!r} is not a string')
            usage_key = raw_usage_key
            _validate_public_key('usage', usage_key)
            canonical_unit = _parse_untrusted_unit(usage_key, raw_unit)
            price_key = cast(str, canonical_unit.get('price_key', usage_key))
            if previous_usage_key := usage_key_by_price_key.get(price_key):
                raise ValueError(f'Duplicate unit price key: {previous_usage_key} and {usage_key} use {price_key}')
            usage_key_by_price_key[price_key] = usage_key

            dimensions = cast(dict[str, str], canonical_unit['dimensions'])
            dimension_set = frozenset(dimensions.items())
            if previous_usage_key := usage_key_by_dimensions.get(dimension_set):
                raise ValueError(f'Duplicate unit dimensions: {previous_usage_key} and {usage_key}')
            usage_key_by_dimensions[dimension_set] = usage_key

            family = dimensions['family']
            per = cast(int, canonical_unit['per'])
            if previous_per := per_by_family.get(family):
                if previous_per != per:
                    raise ValueError(
                        f'Inconsistent per for family dimension {family}: expected {previous_per}, got {per} on {usage_key}'
                    )
            else:
                per_by_family[family] = per

            canonical_units[usage_key] = canonical_unit

        _validate_join_closedness(canonical_units, usage_key_by_dimensions)
        return cls(canonical_units)

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


def _validate_unit_evolution(  # pyright: ignore[reportUnusedFunction]
    previous: UnitRegistry, candidate: UnitRegistry
) -> None:
    """Require a candidate registry to append without changing published unit semantics."""
    previous_order = list(previous.units)
    candidate_order = list(candidate.units)
    for usage_key in previous_order:
        if usage_key not in candidate.units:
            raise ValueError(f'Removed published unit: {usage_key}')

    candidate_old_order = [usage_key for usage_key in candidate_order if usage_key in previous.units]
    if candidate_old_order != previous_order:
        raise ValueError(f'Reordered published units: expected {previous_order!r}, got {candidate_old_order!r}')
    if candidate_order[: len(previous_order)] != previous_order:
        first_inserted = next(usage_key for usage_key in candidate_order if usage_key not in previous.units)
        raise ValueError(f'New unit {first_inserted} must be appended after all published units')

    for usage_key, previous_unit in previous.units.items():
        if candidate.units[usage_key] != previous_unit:
            raise ValueError(f'Redefined published unit: {usage_key}')

    previous_units_by_family: dict[str, list[UnitDef]] = {}
    for old_unit in previous.units.values():
        previous_units_by_family.setdefault(old_unit.dimensions['family'], []).append(old_unit)
    for new_usage_key in candidate_order[len(previous_order) :]:
        new_unit = candidate.units[new_usage_key]
        for old_unit in previous_units_by_family.get(new_unit.dimensions['family'], []):
            if new_unit.dimensions.items() < old_unit.dimensions.items():
                raise ValueError(
                    f'New unit {new_usage_key} is an ancestor or intermediate of published unit {old_unit.usage_key}'
                )


def _unit_display_name(unit: UnitDef) -> str:  # pyright: ignore[reportUnusedFunction]
    dimensions = unit.dimensions
    family = dimensions.get('family')
    direction = dimensions.get('direction')
    modality = dimensions.get('modality')
    parts: list[str]
    use_usage_key = family == 'tool_calls' or (family != 'tokens' and direction is not None and modality is None)
    if use_usage_key:
        parts = [unit.usage_key]
    else:
        parts = []
        if direction is not None:
            parts.append(direction)
        if modality is not None:
            parts.append(modality)
        if family == 'messages':
            parts.append(family)

    handled_dimensions = set(dimensions) if use_usage_key else {'family', 'direction', 'modality'}
    parts.extend(value for key, value in sorted(dimensions.items()) if key not in handled_dimensions)
    if not parts:
        parts.append(unit.usage_key)
    return ' '.join(part.replace('_', ' ').title() for part in parts)


def _unit_per_label(unit: UnitDef) -> str:  # pyright: ignore[reportUnusedFunction]
    family = unit.dimensions.get('family')
    if family == 'tokens' and unit.per == 1_000_000:
        return 'MTok'
    if family == 'requests' and unit.per == 1_000:
        return 'K'
    if family == 'durations' and unit.per == 60:
        return 'Min'
    if family == 'durations' and unit.per == 3_600:
        return 'Hour'
    if unit.per == 1_000_000_000:
        return 'G'
    if unit.per == 1_000_000:
        return 'M'
    if unit.per == 1_000:
        return 'K'
    return str(unit.per)


def _dimension_set(unit: UnitDef) -> frozenset[tuple[str, str]]:
    return frozenset(unit.dimensions.items())


def _is_dimension_subset(maybe_ancestor: UnitDef, unit: UnitDef) -> bool:
    return maybe_ancestor.dimensions.items() <= unit.dimensions.items()


def _object_mapping(value: object, message: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(message)
    return cast(Mapping[object, object], value)


def _validate_public_key(kind: str, key: str) -> None:
    if not _PUBLIC_KEY_PATTERN.fullmatch(key):
        raise ValueError(f'Invalid unit {kind} key: {key!r} is not a public identifier')
    if key in _RESERVED_KEYWORDS or key in _RESERVED_PUBLIC_KEYS:
        raise ValueError(f'Invalid unit {kind} key: {key!r} is reserved')


def _parse_untrusted_unit(usage_key: str, raw_unit_value: object) -> dict[str, Any]:
    raw_unit = _object_mapping(raw_unit_value, f'Invalid unit {usage_key}: expected an object')
    if 'per' not in raw_unit:
        raise ValueError(f'Missing per for unit {usage_key}')
    per = raw_unit['per']
    if isinstance(per, bool) or not isinstance(per, int) or not 1 <= per <= _MAX_SAFE_INTEGER:
        raise ValueError(
            f'Invalid per for unit {usage_key}: expected a positive integer from 1 to {_MAX_SAFE_INTEGER}, got {per!r}'
        )

    raw_price_key = raw_unit.get('price_key', usage_key)
    if not isinstance(raw_price_key, str):
        raise ValueError(f'Invalid unit price key for {usage_key}: expected a string, got {raw_price_key!r}')
    price_key = raw_price_key
    _validate_public_key('price', price_key)

    if 'dimensions' not in raw_unit:
        raise ValueError(f'Missing dimensions for unit {usage_key}')
    raw_dimensions = _object_mapping(
        raw_unit['dimensions'], f'Invalid dimensions for unit {usage_key}: expected an object'
    )
    dimensions: dict[str, str] = {}
    for raw_key, raw_value in raw_dimensions.items():
        if not isinstance(raw_key, str) or not raw_key:
            raise ValueError(f'Invalid dimensions for unit {usage_key}: keys must be non-empty strings')
        if not isinstance(raw_value, str) or not raw_value:
            raise ValueError(f'Invalid dimensions for unit {usage_key}: values must be non-empty strings')
        dimensions[raw_key] = raw_value
    if 'family' not in dimensions:
        raise ValueError(f'Missing required family dimension for unit {usage_key}')

    return {
        'per': per,
        **({'price_key': price_key} if price_key != usage_key else {}),
        'dimensions': dimensions,
    }


def _validate_join_closedness(
    units: Mapping[str, Mapping[str, Any]],
    usage_key_by_dimensions: Mapping[frozenset[tuple[str, str]], str],
) -> None:
    dimensions_by_family: dict[str, list[tuple[str, Mapping[str, str]]]] = {}
    for usage_key, raw_unit in units.items():
        dimensions = cast(Mapping[str, str], raw_unit['dimensions'])
        dimensions_by_family.setdefault(dimensions['family'], []).append((usage_key, dimensions))
    for unit_dimensions in dimensions_by_family.values():
        for (left_key, left), (right_key, right) in combinations(unit_dimensions, 2):
            if any(right.get(key, value) != value for key, value in left.items()):
                continue
            joined_dimensions = frozenset(left.items() | right.items())
            if joined_dimensions not in usage_key_by_dimensions:
                raise ValueError(f'Missing join unit dimensions between {left_key} and {right_key}')


_bundled_registry: UnitRegistry | None = None
_active_registry: UnitRegistry | None = None


def _get_registry() -> UnitRegistry:  # pyright: ignore[reportUnusedFunction]
    global _bundled_registry

    if _active_registry is not None:
        return _active_registry
    if _bundled_registry is not None:
        return _bundled_registry

    from genai_prices.data_units import unit_data

    _bundled_registry = UnitRegistry(unit_data)
    return _bundled_registry


def _set_active_registry(registry: UnitRegistry | None) -> None:  # pyright: ignore[reportUnusedFunction]
    """Select a replacement registry, or restore lazy bundled-registry lookup."""
    global _active_registry
    _active_registry = registry
