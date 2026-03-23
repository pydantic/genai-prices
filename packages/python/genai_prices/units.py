"""Token unit registry — defines unit families, dimensions, and unit definitions.

Unit data is loaded from units_data.json, generated from prices/units.yml via `make package-data`.
"""

from __future__ import annotations as _annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UnitDef:
    """Definition of a single pricing unit."""

    id: str
    family_id: str
    usage_key: str
    dimensions: dict[str, str]


@dataclass(frozen=True)
class UnitFamily:
    """A family of pricing units that share a normalization factor."""

    id: str
    per: int
    description: str
    dimensions: dict[str, list[str]]
    units: dict[str, UnitDef]


def _load_families() -> dict[str, UnitFamily]:
    """Load unit families from the generated JSON data file."""
    data_path = Path(__file__).parent / 'units_data.json'
    raw = json.loads(data_path.read_bytes())
    families: dict[str, UnitFamily] = {}
    for family_id, fam_data in raw['families'].items():
        units: dict[str, UnitDef] = {}
        for unit_id, unit_data in fam_data['units'].items():
            units[unit_id] = UnitDef(
                id=unit_id,
                family_id=family_id,
                usage_key=unit_data['usage_key'],
                dimensions=unit_data['dimensions'],
            )
        families[family_id] = UnitFamily(
            id=family_id,
            per=fam_data['per'],
            description=fam_data['description'],
            dimensions=fam_data['dimensions'],
            units=units,
        )
    return families


_FAMILIES = _load_families()
TOKENS_FAMILY = _FAMILIES['tokens']
_ALL_UNITS: dict[str, UnitDef] = {uid: unit for fam in _FAMILIES.values() for uid, unit in fam.units.items()}

# Mapping from current ModelPrice field names to registry unit IDs.
# Only needed during Phase 1 while ModelPrice uses fixed fields.
FIELD_TO_UNIT: dict[str, str] = {
    'input_mtok': 'input_mtok',
    'output_mtok': 'output_mtok',
    'cache_read_mtok': 'cache_read_mtok',
    'cache_write_mtok': 'cache_write_mtok',
    'input_audio_mtok': 'input_audio_mtok',
    'cache_audio_read_mtok': 'cache_read_audio_mtok',  # field name differs from unit ID
    'output_audio_mtok': 'output_audio_mtok',
}


def get_family(family_id: str) -> UnitFamily:
    """Look up a unit family by ID. Raises KeyError if not found."""
    return _FAMILIES[family_id]


def get_unit(unit_id: str) -> UnitDef:
    """Look up a unit definition by ID. Raises KeyError if not found."""
    return _ALL_UNITS[unit_id]
