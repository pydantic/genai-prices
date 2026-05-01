from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

__all__ = 'UnitDef', 'UnitFamily', 'UnitRegistry'


@dataclass(eq=False)
class UnitDef:
    usage_key: str
    price_key: str
    family_id: str
    family: UnitFamily
    dimensions: dict[str, str]


@dataclass(eq=False)
class UnitFamily:
    id: str
    per: int
    description: str
    units: dict[str, UnitDef] = field(default_factory=dict)


class UnitRegistry:
    families: dict[str, UnitFamily]
    units: dict[str, UnitDef]
    price_keys: dict[str, str]
    _units_by_dimension: dict[str, dict[frozenset[tuple[str, str]], UnitDef]]
    _ancestor_usage_keys: dict[str, frozenset[str]]

    def __init__(self, raw_families: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        """Parse raw unit-family dictionaries into indexed runtime objects."""
        self.families = {}
        self.units = {}
        self.price_keys = {}
        self._units_by_dimension = {}
        self._ancestor_usage_keys = {}

        for family_id, raw_family in (raw_families or {}).items():
            family = UnitFamily(
                id=family_id,
                per=cast(int, raw_family['per']),
                description=cast(str, raw_family.get('description', '')),
            )
            self.families[family_id] = family
            family_dimensions: dict[frozenset[tuple[str, str]], UnitDef] = {}
            self._units_by_dimension[family_id] = family_dimensions

            raw_units = cast(Mapping[str, Mapping[str, Any]], raw_family.get('units', {}))
            for usage_key, raw_unit in raw_units.items():
                unit = UnitDef(
                    usage_key=usage_key,
                    price_key=cast(str, raw_unit.get('price_key', usage_key)),
                    family_id=family_id,
                    family=family,
                    dimensions=dict(cast(Mapping[str, str], raw_unit.get('dimensions', {}))),
                )
                family.units[usage_key] = unit
                self.units[usage_key] = unit
                self.price_keys[unit.price_key] = usage_key
                family_dimensions[self._dimension_set(unit)] = unit

        for usage_key, unit in self.units.items():
            self._ancestor_usage_keys[usage_key] = frozenset(
                maybe_ancestor.usage_key
                for maybe_ancestor in unit.family.units.values()
                if maybe_ancestor is not unit and self._is_dimension_subset(maybe_ancestor, unit)
            )

    @staticmethod
    def _dimension_set(unit: UnitDef) -> frozenset[tuple[str, str]]:
        return frozenset(unit.dimensions.items())

    @staticmethod
    def _is_dimension_subset(maybe_ancestor: UnitDef, unit: UnitDef) -> bool:
        return maybe_ancestor.dimensions.items() <= unit.dimensions.items()

    @staticmethod
    def are_compatible(a: UnitDef, b: UnitDef) -> bool:
        """Return whether two units can overlap without conflicting dimensions."""
        if a.family is not b.family:
            return False

        return all(b.dimensions.get(key, value) == value for key, value in a.dimensions.items())

    @staticmethod
    def is_ancestor_or_self(ancestor: UnitDef, descendant: UnitDef) -> bool:
        """Return whether ancestor contains descendant within the same family."""
        return ancestor.family is descendant.family and UnitRegistry._is_dimension_subset(ancestor, descendant)
