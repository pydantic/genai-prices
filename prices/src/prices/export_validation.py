from __future__ import annotations

from collections.abc import Mapping
from itertools import combinations
from typing import Any, cast

from genai_prices.units import UnitRegistry

from .prices_types import Provider


def validate_units(raw_units: Mapping[str, Mapping[str, Any]]) -> UnitRegistry:
    """Validate publishable flat unit data and return the indexed registry."""
    runtime_units: dict[str, dict[str, Any]] = {}
    dimension_requirements_by_usage_key: dict[str, dict[str, dict[str, str]]] = {}
    for usage_key, raw_unit in raw_units.items():
        dimensions = dict(cast(Mapping[str, str], raw_unit.get('dimensions', {})))
        dimension_requirements = {
            conditional_key: dict(required_dimensions)
            for conditional_key, required_dimensions in cast(
                Mapping[str, Mapping[str, str]], raw_unit.get('dimension_requirements', {})
            ).items()
        }
        _validate_dimension_requirements(usage_key, dimensions, dimension_requirements)
        dimension_requirements_by_usage_key[usage_key] = dimension_requirements
        runtime_unit = {'per': raw_unit.get('per'), 'dimensions': dimensions}
        if 'price_key' in raw_unit:
            runtime_unit['price_key'] = raw_unit['price_key']
        runtime_units[usage_key] = runtime_unit

    registry = UnitRegistry.from_untrusted(runtime_units)
    _validate_source_interval_closure(registry, dimension_requirements_by_usage_key)
    return registry


def validate_export_payload(providers: list[Provider], units: Mapping[str, Mapping[str, Any]]) -> UnitRegistry:
    """Validate registry structure, provider model prices, and extractor destinations before export."""
    from prices.package_data import validate_provider_extractor_destinations, validate_provider_model_prices

    registry = validate_units(units)
    validate_provider_model_prices(providers, registry)
    validate_provider_extractor_destinations(providers, registry)
    return registry


def validate_unit_evolution(
    previous_units: Mapping[str, Mapping[str, Any]],
    candidate_units: Mapping[str, Mapping[str, Any]],
) -> None:
    """Require a published unit registry to evolve without changing existing relationships."""
    for usage_key, previous_unit in previous_units.items():
        candidate_unit = candidate_units.get(usage_key)
        if candidate_unit is None:
            raise ValueError(f'Published unit removed: {usage_key}')

        previous_definition = _resolved_unit_definition(usage_key, previous_unit)
        candidate_definition = _resolved_unit_definition(usage_key, candidate_unit)
        if candidate_definition != previous_definition:
            raise ValueError(
                f'Published unit changed: {usage_key}: expected {previous_definition!r}, got {candidate_definition!r}'
            )

    previous_dimensions = {
        usage_key: frozenset(cast(Mapping[str, str], unit['dimensions']).items())
        for usage_key, unit in previous_units.items()
    }
    for usage_key, candidate_unit in candidate_units.items():
        if usage_key in previous_units:
            continue

        candidate_dimensions = frozenset(cast(Mapping[str, str], candidate_unit['dimensions']).items())
        for previous_usage_key, old_dimensions in previous_dimensions.items():
            if candidate_dimensions < old_dimensions:
                raise ValueError(
                    f'New unit {usage_key} would become an ancestor of published unit {previous_usage_key}'
                )


def _resolved_unit_definition(
    usage_key: str, raw_unit: Mapping[str, Any]
) -> tuple[str, int, frozenset[tuple[str, str]]]:
    return (
        cast(str, raw_unit.get('price_key', usage_key)),
        cast(int, raw_unit['per']),
        frozenset(cast(Mapping[str, str], raw_unit['dimensions']).items()),
    )


def _validate_dimension_requirements(
    usage_key: str,
    dimensions: Mapping[str, str],
    dimension_requirements: Mapping[str, Mapping[str, str]],
) -> None:
    for conditional_key, required_dimensions in dimension_requirements.items():
        if conditional_key not in dimensions:
            raise ValueError(f'Dimension requirement trigger {conditional_key} is not a dimension of unit {usage_key}')
        if not required_dimensions.items() <= dimensions.items():
            missing = ', '.join(
                f'{key}={value}' for key, value in sorted(required_dimensions.items() - dimensions.items())
            )
            raise ValueError(f'Unsatisfied dimension requirement for unit {usage_key}: {missing}')


def _validate_source_interval_closure(
    registry: UnitRegistry,
    dimension_requirements_by_usage_key: Mapping[str, Mapping[str, Mapping[str, str]]],
) -> None:
    units_by_dimension = registry._units_by_dimension  # pyright: ignore[reportPrivateUsage]
    for ancestor in registry.units.values():
        for descendant in registry.units.values():
            if ancestor is descendant or not ancestor.dimensions.items() <= descendant.dimensions.items():
                continue

            added_dimensions = descendant.dimensions.items() - ancestor.dimensions.items()
            for size in range(1, len(added_dimensions)):
                for added_subset in combinations(added_dimensions, size):
                    required_dimensions = frozenset(ancestor.dimensions.items() | set(added_subset))
                    if not _source_requirements_are_satisfied(
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


def _source_requirements_are_satisfied(
    dimension_requirements: Mapping[str, Mapping[str, str]], dimensions: Mapping[str, str]
) -> bool:
    return all(
        conditional_key not in dimensions or required_dimensions.items() <= dimensions.items()
        for conditional_key, required_dimensions in dimension_requirements.items()
    )
