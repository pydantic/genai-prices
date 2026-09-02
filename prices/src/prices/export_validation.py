from __future__ import annotations

import keyword
import re
from collections.abc import Mapping
from itertools import combinations
from typing import Any, cast

from genai_prices.units import UnitDef, UnitRegistry

from .prices_types import Provider

RuntimeUnitProjection = dict[str, dict[str, object]]
ImplicationTriple = tuple[str, str, str]
NormalizedImplications = dict[str, tuple[ImplicationTriple, ...]]

_PUBLIC_KEY_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
# Usage, price, and dimension keys cross all three runtimes, so keep one shared blacklist.
_RESERVED_PUBLIC_KEYS = frozenset(
    {
        *keyword.kwlist,
        '__proto__',
        'arguments',
        'await',
        'break',
        'case',
        'catch',
        'chan',
        'class',
        'const',
        'constructor',
        'continue',
        'debugger',
        'default',
        'defer',
        'delete',
        'do',
        'else',
        'enum',
        'eval',
        'export',
        'extends',
        'false',
        'fallthrough',
        'finally',
        'for',
        'function',
        'func',
        'go',
        'goto',
        'if',
        'implements',
        'import',
        'in',
        'instanceof',
        'interface',
        'key',  # The Go generator would emit UsageKey, which is the public key type.
        'let',
        'map',
        'new',
        'null',
        'package',
        'private',
        'prototype',
        'protected',
        'public',
        'range',
        'return',
        'select',
        'static',
        'struct',
        'super',
        'switch',
        'this',
        'throw',
        'true',
        'try',
        'type',
        'typeof',
        'var',
        'void',
        'while',
        'with',
        'yield',
    }
)


def public_unit_key_schema() -> dict[str, Any]:
    """Return the JSON Schema shared by runtime unit usage and price keys."""
    return {
        'allOf': [
            {'pattern': r'^[A-Za-z]'},
            {'not': {'pattern': r'[^A-Za-z0-9_]'}},
            {'not': {'enum': sorted(_RESERVED_PUBLIC_KEYS)}},
        ],
        'type': 'string',
    }


def validate_units(raw_units: Mapping[str, Mapping[str, Any]]) -> UnitRegistry:
    """Validate publishable flat unit data and return the indexed registry."""
    # This validates the current registry only. Cross-release compatibility of
    # source unit data is a maintainer responsibility, not a build-time diff check.
    registry = validate_runtime_unit_projection(raw_units)
    normalized_implications = normalize_conditional_implications(raw_units)
    dimension_requirements_by_usage_key = _requirements_from_normalized_implications(normalized_implications)
    _validate_interval_closure(registry, dimension_requirements_by_usage_key)
    return registry


def runtime_unit_projection(raw_units: Mapping[str, Mapping[str, object]]) -> RuntimeUnitProjection:
    """Return the ordered, runtime-semantic projection of source unit data."""
    projection: RuntimeUnitProjection = {}
    for usage_key, raw_unit in raw_units.items():
        runtime_unit: dict[str, object] = {'per': raw_unit['per']}
        price_key = raw_unit.get('price_key', usage_key)
        if price_key != usage_key:
            runtime_unit['price_key'] = price_key
        runtime_unit['dimensions'] = dict(cast(Mapping[str, object], raw_unit.get('dimensions', {})))
        projection[usage_key] = runtime_unit
    return projection


def normalize_conditional_implications(
    raw_units: Mapping[str, Mapping[str, object]],
) -> NormalizedImplications:
    """Normalize each source unit's conditional rules to canonical transitive triples."""
    normalized: NormalizedImplications = {}
    for usage_key, raw_unit in raw_units.items():
        dimensions = dict(cast(Mapping[str, str], raw_unit.get('dimensions', {})))
        requirements = _parse_dimension_requirements(usage_key, raw_unit.get('dimension_requirements', {}))
        normalized[usage_key] = _normalize_unit_implications(usage_key, dimensions, requirements)
    return normalized


def validate_runtime_unit_projection(raw_units: Mapping[str, Mapping[str, object]]) -> UnitRegistry:
    """Validate invariants available from the runtime unit wire projection."""
    raw_units_mapping = _object_mapping(raw_units, 'Invalid units: expected a mapping')

    price_keys: set[str] = set()
    per_by_family: dict[str, int] = {}
    dimension_sets: dict[frozenset[tuple[str, str]], str] = {}
    validated_raw_units: dict[str, Mapping[str, object]] = {}

    for raw_usage_key, raw_unit_value in raw_units_mapping.items():
        if not isinstance(raw_usage_key, str):
            raise ValueError(f'Invalid unit usage key: {raw_usage_key!r} is not a string')
        usage_key = raw_usage_key
        _validate_public_key('usage', usage_key)

        if not isinstance(raw_unit_value, Mapping):
            raise ValueError(f'Invalid unit {usage_key}: expected a mapping')
        raw_unit = cast(Mapping[str, object], raw_unit_value)
        validated_raw_units[usage_key] = raw_unit

        raw_price_key = raw_unit.get('price_key', usage_key)
        if not isinstance(raw_price_key, str):
            raise ValueError(f'Invalid unit price key for {usage_key}: expected a string, got {raw_price_key!r}')
        price_key = raw_price_key
        _validate_public_key('price', price_key)
        if price_key in price_keys:
            raise ValueError(f'Duplicate unit price key: {price_key}')
        price_keys.add(price_key)

        if 'per' not in raw_unit:
            raise ValueError(f'Missing per for unit {usage_key}')
        per = raw_unit['per']
        if isinstance(per, bool) or not isinstance(per, int) or not 1 <= per <= _MAX_SAFE_INTEGER:
            raise ValueError(
                f'Invalid per for unit {usage_key}: expected a positive integer from 1 to '
                f'{_MAX_SAFE_INTEGER}, got {per!r}'
            )

        if 'dimensions' not in raw_unit:
            raise ValueError(f'Missing dimensions for unit {usage_key}')
        raw_dimensions = raw_unit['dimensions']
        if not isinstance(raw_dimensions, Mapping):
            raise ValueError(f'Invalid dimensions for unit {usage_key}: expected a mapping')

        dimensions: dict[str, str] = {}
        for raw_dimension_key, raw_dimension_value in cast(Mapping[object, object], raw_dimensions).items():
            if not isinstance(raw_dimension_key, str):
                raise ValueError(f'Invalid unit dimension key: {raw_dimension_key!r} is not a public identifier')
            if not raw_dimension_key:
                raise ValueError(f'Invalid dimensions for unit {usage_key}: keys must be non-empty strings')
            _validate_public_key('dimension', raw_dimension_key)
            if not isinstance(raw_dimension_value, str) or not raw_dimension_value:
                raise ValueError(f'Invalid dimensions for unit {usage_key}: values must be non-empty strings')
            dimensions[raw_dimension_key] = raw_dimension_value

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

    projection = runtime_unit_projection(validated_raw_units)
    registry = UnitRegistry(projection)
    _validate_join_closedness(registry)
    return registry


def validate_unit_evolution(
    previous_units: RuntimeUnitProjection,
    previous_implications: NormalizedImplications,
    candidate_units: Mapping[str, Mapping[str, object]],
) -> None:
    """Validate append-only source evolution from a published runtime projection."""
    previous_projection = runtime_unit_projection(previous_units)
    previous_registry = validate_runtime_unit_projection(previous_projection)
    candidate_registry = validate_units(candidate_units)
    candidate_projection = runtime_unit_projection(candidate_units)
    candidate_implications = normalize_conditional_implications(candidate_units)

    previous_order = list(previous_projection)
    candidate_order = list(candidate_projection)
    missing_usage_keys = [usage_key for usage_key in previous_order if usage_key not in candidate_projection]
    if missing_usage_keys:
        raise ValueError(f'Removed published unit: {missing_usage_keys[0]}')

    candidate_old_order = [usage_key for usage_key in candidate_order if usage_key in previous_projection]
    if candidate_old_order != previous_order:
        raise ValueError(f'Reordered published units: expected {previous_order!r}, got {candidate_old_order!r}')
    if candidate_order[: len(previous_order)] != previous_order:
        first_inserted = next(usage_key for usage_key in candidate_order if usage_key not in previous_projection)
        raise ValueError(f'New unit {first_inserted} must be appended after all published units')

    for usage_key in previous_order:
        if candidate_projection[usage_key] != previous_projection[usage_key]:
            raise ValueError(f'Redefined published unit: {usage_key}')

        if usage_key not in previous_implications:
            raise ValueError(f'Missing published conditional implications for unit {usage_key}')
        if candidate_implications[usage_key] != previous_implications[usage_key]:
            raise ValueError(f'Changed published conditional implications for unit {usage_key}')

    for new_usage_key in candidate_order[len(previous_order) :]:
        new_unit = candidate_registry.units[new_usage_key]
        for old_usage_key in previous_order:
            old_unit = previous_registry.units[old_usage_key]
            if new_unit.dimensions.items() < old_unit.dimensions.items():
                raise ValueError(
                    f'New unit {new_usage_key} is an ancestor or intermediate of published unit {old_usage_key}'
                )


def _object_mapping(value: object, message: str) -> Mapping[object, object]:
    if not isinstance(value, Mapping):
        raise ValueError(message)
    return cast(Mapping[object, object], value)


def validate_export_payload(providers: list[Provider], units: Mapping[str, Mapping[str, Any]]) -> UnitRegistry:
    """Validate registry structure, provider model prices, and provider extractors before export."""
    from prices.go_identifiers import validate_go_usage_key_identifiers
    from prices.package_data import (
        validate_provider_extractor_destinations,
        validate_provider_extractor_reasoning_coverage,
        validate_provider_model_prices,
    )

    registry = validate_units(units)
    validate_go_usage_key_identifiers(registry.units)
    validate_provider_model_prices(providers, registry)
    validate_provider_extractor_destinations(providers, registry)
    validate_provider_extractor_reasoning_coverage(providers)
    return registry


def _validate_public_key(kind: str, key: str) -> None:
    if not _PUBLIC_KEY_PATTERN.fullmatch(key):
        raise ValueError(f'Invalid unit {kind} key: {key!r} is not a public identifier')
    if key.startswith('_'):
        raise ValueError(f'Invalid unit {kind} key: {key!r} must not start with "_"')
    if key in _RESERVED_PUBLIC_KEYS:
        raise ValueError(f'Invalid unit {kind} key: {key!r} is reserved')


def _parse_dimension_requirements(usage_key: str, raw_requirements: Any) -> dict[str, dict[str, str]]:
    if not isinstance(raw_requirements, Mapping):
        raise ValueError(f'Invalid dimension_requirements for unit {usage_key}: expected a mapping')

    dimension_requirements: dict[str, dict[str, str]] = {}
    for conditional_key, raw_required_dimensions in cast(Mapping[object, object], raw_requirements).items():
        if not isinstance(conditional_key, str):
            raise ValueError(f'Invalid dimension_requirements for unit {usage_key}: trigger keys must be strings')
        if not isinstance(raw_required_dimensions, Mapping):
            raise ValueError(
                f'Invalid dimension_requirements for unit {usage_key}: '
                f'requirement for {conditional_key!r} must be a mapping'
            )

        required_dimensions: dict[str, str] = {}
        for dimension_key, dimension_value in cast(Mapping[object, object], raw_required_dimensions).items():
            if not isinstance(dimension_key, str) or not isinstance(dimension_value, str):
                raise ValueError(
                    f'Invalid dimension_requirements for unit {usage_key}: '
                    f'requirement for {conditional_key!r} must map string dimension keys to string values'
                )
            required_dimensions[dimension_key] = dimension_value
        dimension_requirements[conditional_key] = required_dimensions

    return dimension_requirements


def _validate_dimension_requirements(
    usage_key: str,
    dimensions: Mapping[str, str],
    dimension_requirements: Mapping[str, Mapping[str, str]],
) -> None:
    for required_dimensions in dimension_requirements.values():
        if not required_dimensions.items() <= dimensions.items():
            missing = ', '.join(
                f'{key}={value}' for key, value in sorted(required_dimensions.items() - dimensions.items())
            )
            raise ValueError(f'Unsatisfied dimension requirement for unit {usage_key}: {missing}')


def _normalize_unit_implications(
    usage_key: str,
    dimensions: Mapping[str, str],
    dimension_requirements: Mapping[str, Mapping[str, str]],
) -> tuple[ImplicationTriple, ...]:
    for conditional_key in dimension_requirements:
        if conditional_key not in dimensions:
            raise ValueError(f'Dimension requirement trigger {conditional_key} is not a dimension of unit {usage_key}')

    _expand_implied_assignments(usage_key, dimension_requirements, dimension_requirements)
    _validate_dimension_requirements(usage_key, dimensions, dimension_requirements)

    triples: set[ImplicationTriple] = set()
    for root_trigger in dimension_requirements:
        assignments = _expand_implied_assignments(
            usage_key,
            {root_trigger: dimension_requirements[root_trigger]},
            dimension_requirements,
        )
        for required_key, required_value in assignments.items():
            triples.add((root_trigger, required_key, required_value))

    return tuple(sorted(triples))


def _expand_implied_assignments(
    usage_key: str,
    initial_requirements: Mapping[str, Mapping[str, str]],
    all_requirements: Mapping[str, Mapping[str, str]],
) -> dict[str, str]:
    pending = list(initial_requirements)
    expanded: set[str] = set()
    assignments: dict[str, str] = {}

    while pending:
        trigger = pending.pop()
        if trigger in expanded:
            continue
        expanded.add(trigger)

        required_dimensions = (
            initial_requirements[trigger] if trigger in initial_requirements else all_requirements.get(trigger, {})
        )
        for required_key, required_value in required_dimensions.items():
            existing_value = assignments.get(required_key)
            if existing_value is not None and existing_value != required_value:
                raise ValueError(
                    f'Conflicting implied dimension assignment for unit {usage_key}: '
                    f'{required_key}={existing_value} and {required_key}={required_value}'
                )
            assignments[required_key] = required_value
            if required_key in all_requirements:
                pending.append(required_key)

    return assignments


def _requirements_from_normalized_implications(
    normalized_implications: NormalizedImplications,
) -> dict[str, dict[str, dict[str, str]]]:
    requirements_by_usage_key: dict[str, dict[str, dict[str, str]]] = {}
    for usage_key, implications in normalized_implications.items():
        requirements: dict[str, dict[str, str]] = {}
        for trigger, required_key, required_value in implications:
            requirements.setdefault(trigger, {})[required_key] = required_value
        requirements_by_usage_key[usage_key] = requirements
    return requirements_by_usage_key


def _validate_interval_closure(
    registry: UnitRegistry,
    dimension_requirements_by_usage_key: Mapping[str, Mapping[str, Mapping[str, str]]],
) -> None:
    units_by_dimension = registry._units_by_dimension  # pyright: ignore[reportPrivateUsage]
    for ancestor in registry.units.values():
        for descendant in registry.units.values():
            if ancestor is descendant or not _is_dimension_subset(ancestor, descendant):
                continue

            added_dimensions = descendant.dimensions.items() - ancestor.dimensions.items()
            for size in range(1, len(added_dimensions)):
                for added_subset in combinations(added_dimensions, size):
                    required_dimensions = frozenset(ancestor.dimensions.items() | set(added_subset))
                    if not _requirements_are_satisfied_by(
                        dimension_requirements_by_usage_key[descendant.usage_key], dict(required_dimensions)
                    ):
                        continue
                    if required_dimensions in units_by_dimension:
                        continue

                    missing_dimensions = ', '.join(f'{key}={value}' for key, value in sorted(required_dimensions))
                    raise ValueError(
                        f'Missing intermediate unit dimensions between {ancestor.usage_key} and '
                        f'{descendant.usage_key}: {missing_dimensions}'
                    )


def _requirements_are_satisfied_by(
    dimension_requirements: Mapping[str, Mapping[str, str]], dimensions: Mapping[str, str]
) -> bool:
    return all(
        conditional_key not in dimensions or required_dimensions.items() <= dimensions.items()
        for conditional_key, required_dimensions in dimension_requirements.items()
    )


def _validate_join_closedness(registry: UnitRegistry) -> None:
    units_by_dimension = registry._units_by_dimension  # pyright: ignore[reportPrivateUsage]
    for a, b in combinations(registry.units.values(), 2):
        if not a.is_compatible_with(b):
            continue

        required_dimensions = frozenset(a.dimensions.items() | b.dimensions.items())
        if required_dimensions in units_by_dimension:
            continue

        missing_dimensions = ', '.join(f'{key}={value}' for key, value in sorted(required_dimensions))
        raise ValueError(f'Missing join unit dimensions between {a.usage_key} and {b.usage_key}: {missing_dimensions}')


def _is_dimension_subset(maybe_ancestor: UnitDef, unit: UnitDef) -> bool:
    return maybe_ancestor.dimensions.items() <= unit.dimensions.items()
