from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast


@dataclass(eq=False)
class UnitDef:
    usage_key: str
    price_key: str
    per: int
    dimensions: dict[str, str]

    def is_compatible_with(self, other: UnitDef) -> bool:
        """Return whether two units can overlap without conflicting dimensions."""
        return all(other.dimensions.get(key, value) == value for key, value in self.dimensions.items())


class UnitRegistry:
    units: dict[str, UnitDef]
    _units_by_price_key: dict[str, UnitDef]
    _units_by_dimension: dict[frozenset[tuple[str, str]], UnitDef]
    _ancestor_usage_keys: dict[str, frozenset[str]]

    def __init__(self, raw_units: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        """Parse raw unit dictionaries into indexed runtime objects."""
        self.units = {}
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

            self.units[usage_key] = unit
            self._units_by_price_key[unit.price_key] = unit
            self._units_by_dimension[dimension_set] = unit

        for usage_key, unit in self.units.items():
            self._ancestor_usage_keys[usage_key] = frozenset(
                maybe_ancestor.usage_key
                for maybe_ancestor in self.units.values()
                if maybe_ancestor is not unit and _is_dimension_subset(maybe_ancestor, unit)
            )

    def unit_for_price_key(self, price_key: str) -> UnitDef:
        """Return the registered unit priced by price_key."""
        return self._units_by_price_key[price_key]

    def reported_usage_keys(self) -> frozenset[str]:
        """Return registered keys callers may report, excluding the pricing-only requests unit."""
        return frozenset(usage_key for usage_key in self.units if usage_key != 'requests')

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


def _set_registry(registry: UnitRegistry | None) -> None:  # pyright: ignore[reportUnusedFunction]
    """Replace the active global unit registry, or restore bundled units when passed None."""
    global _active_registry

    _active_registry = registry
    # Phase 5 registry-keyed caches should be cleared here when they exist.
