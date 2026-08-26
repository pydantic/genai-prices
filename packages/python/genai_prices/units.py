from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast


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


_bundled_registry: UnitRegistry | None = None


def _get_registry() -> UnitRegistry:  # pyright: ignore[reportUnusedFunction]
    global _bundled_registry

    if _bundled_registry is not None:
        return _bundled_registry

    from genai_prices.data_units import unit_data

    _bundled_registry = UnitRegistry(unit_data)
    return _bundled_registry
