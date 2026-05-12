from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, cast


@dataclass(eq=False)
class UnitDef:
    usage_key: str
    price_key: str
    family_id: str
    family: UnitFamily
    dimensions: dict[str, str]

    def is_compatible_with(self, other: UnitDef) -> bool:
        """Return whether two units can overlap without conflicting dimensions."""
        if self.family is not other.family:
            return False

        return all(other.dimensions.get(key, value) == value for key, value in self.dimensions.items())


@dataclass(eq=False)
class UnitFamily:
    id: str
    per: int
    description: str
    units: dict[str, UnitDef] = field(default_factory=dict)
    units_by_dimension: dict[frozenset[tuple[str, str]], UnitDef] = field(default_factory=dict)

    def find_join(self, a: UnitDef, b: UnitDef) -> UnitDef | None:
        """Return the most specific registered unit joining two family units, if present."""
        if not a.is_compatible_with(b):
            return None

        return self.units_by_dimension.get(frozenset(a.dimensions.items() | b.dimensions.items()))


class UnitRegistry:
    families: dict[str, UnitFamily]
    units: dict[str, UnitDef]
    _units_by_price_key: dict[str, UnitDef]
    _ancestor_usage_keys: dict[str, frozenset[str]]

    def __init__(self, raw_families: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        """Parse raw unit-family dictionaries into indexed runtime objects."""
        self.families = {}
        self.units = {}
        self._units_by_price_key = {}
        self._ancestor_usage_keys = {}

        for family_id, raw_family in (raw_families or {}).items():
            family = UnitFamily(
                id=family_id,
                per=cast(int, raw_family['per']),
                description=cast(str, raw_family.get('description', '')),
            )
            self.families[family_id] = family

            raw_units = cast(Mapping[str, Mapping[str, Any]], raw_family.get('units', {}))
            for usage_key, raw_unit in raw_units.items():
                if usage_key in self.units:
                    raise ValueError(f'Duplicate unit usage key: {usage_key}')

                unit = UnitDef(
                    usage_key=usage_key,
                    price_key=cast(str, raw_unit.get('price_key', usage_key)),
                    family_id=family_id,
                    family=family,
                    dimensions=dict(cast(Mapping[str, str], raw_unit.get('dimensions', {}))),
                )
                if unit.price_key in self._units_by_price_key:
                    raise ValueError(f'Duplicate unit price key: {unit.price_key}')

                dimension_set = _dimension_set(unit)
                if existing_unit := family.units_by_dimension.get(dimension_set):
                    raise ValueError(
                        f'Duplicate dimensions in unit family {family_id}: {existing_unit.usage_key} and {usage_key}'
                    )

                family.units[usage_key] = unit
                self.units[usage_key] = unit
                self._units_by_price_key[unit.price_key] = unit
                family.units_by_dimension[dimension_set] = unit

        for usage_key, unit in self.units.items():
            self._ancestor_usage_keys[usage_key] = frozenset(
                maybe_ancestor.usage_key
                for maybe_ancestor in unit.family.units.values()
                if maybe_ancestor is not unit and _is_dimension_subset(maybe_ancestor, unit)
            )

        self._validate_interval_closure()

    def unit_for_price_key(self, price_key: str) -> UnitDef:
        """Return the registered unit priced by price_key."""
        return self._units_by_price_key[price_key]

    def reported_usage_keys(self) -> frozenset[str]:
        """Return registered keys callers may report, excluding Phase 1 pricing-only requests."""
        return frozenset(usage_key for usage_key in self.units if usage_key != 'requests')

    def ancestor_usage_keys(self, usage_key: str) -> frozenset[str]:
        return self._ancestor_usage_keys[usage_key]

    def _validate_interval_closure(self) -> None:
        for family in self.families.values():
            for ancestor in family.units.values():
                for descendant in family.units.values():
                    if ancestor is descendant or not _is_dimension_subset(ancestor, descendant):
                        continue

                    added_dimensions = descendant.dimensions.items() - ancestor.dimensions.items()
                    for size in range(1, len(added_dimensions)):
                        for added_subset in combinations(added_dimensions, size):
                            required_dimensions = frozenset(ancestor.dimensions.items() | set(added_subset))
                            if required_dimensions not in family.units_by_dimension:
                                missing_dimensions = ', '.join(
                                    f'{key}={value}' for key, value in sorted(required_dimensions)
                                )
                                raise ValueError(
                                    f'Missing intermediate unit dimensions in family {family.id} '
                                    f'between {ancestor.usage_key} and {descendant.usage_key}: '
                                    f'{missing_dimensions}'
                                )


def _dimension_set(unit: UnitDef) -> frozenset[tuple[str, str]]:
    return frozenset(unit.dimensions.items())


def _is_dimension_subset(maybe_ancestor: UnitDef, unit: UnitDef) -> bool:
    return maybe_ancestor.dimensions.items() <= unit.dimensions.items()


_bundled_registry: UnitRegistry | None = None
_active_registry: UnitRegistry | None = None


def _get_registry() -> UnitRegistry:  # pyright: ignore[reportUnusedFunction]
    global _bundled_registry

    if _active_registry is not None:
        return _active_registry

    if _bundled_registry is not None:
        return _bundled_registry

    from genai_prices.data_units import unit_families_data

    _bundled_registry = UnitRegistry(unit_families_data)
    return _bundled_registry


def _set_registry(registry: UnitRegistry | None) -> None:  # pyright: ignore[reportUnusedFunction]
    """Replace the active global unit registry, or restore bundled units when passed None."""
    global _active_registry

    _active_registry = registry
    # Phase 5 registry-keyed caches should be cleared here when they exist.
