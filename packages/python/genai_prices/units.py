"""Token unit registry — defines unit families, dimensions, and unit definitions.

Unit data is loaded from units_data.json, generated from prices/units.yml via `make package-data`.
"""

from __future__ import annotations as _annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator


class UnitDef(BaseModel):
    """Definition of a single pricing unit."""

    model_config = ConfigDict(frozen=True)

    id: str
    family_id: str
    usage_key: str
    dimensions: dict[str, str]


class RawUnitDef(BaseModel):
    """JSON shape for a unit definition (no id/family_id — those come from dict keys)."""

    usage_key: str
    dimensions: dict[str, str]


class UnitFamily(BaseModel):
    """A family of pricing units that share a normalization factor."""

    model_config = ConfigDict(frozen=True)

    id: str
    per: int
    description: str
    dimensions: dict[str, list[str]]
    units: dict[str, UnitDef]


class RawUnitFamily(BaseModel):
    per: int
    description: str
    dimensions: dict[str, list[str]]
    units: dict[str, RawUnitDef]


class RawUnitsData(BaseModel):
    families: dict[str, RawUnitFamily]

    @model_validator(mode='after')
    def _validate_dimensions(self) -> RawUnitsData:
        for family_id, fam in self.families.items():
            for unit_id, unit in fam.units.items():
                for dim_key, dim_val in unit.dimensions.items():
                    if dim_key not in fam.dimensions:
                        raise ValueError(f'{family_id}/{unit_id}: unknown dimension key {dim_key!r}')
                    if dim_val not in fam.dimensions[dim_key]:
                        raise ValueError(f'{family_id}/{unit_id}: invalid value {dim_val!r} for dimension {dim_key!r}')
        return self


def _load_families() -> dict[str, UnitFamily]:
    """Load and validate unit families from the generated JSON data file."""
    data_path = Path(__file__).parent / 'units_data.json'
    raw = RawUnitsData.model_validate_json(data_path.read_bytes())
    families: dict[str, UnitFamily] = {}
    for family_id, fam_data in raw.families.items():
        units: dict[str, UnitDef] = {}
        for unit_id, unit_data in fam_data.units.items():
            units[unit_id] = UnitDef(
                id=unit_id,
                family_id=family_id,
                usage_key=unit_data.usage_key,
                dimensions=unit_data.dimensions,
            )
        families[family_id] = UnitFamily(
            id=family_id,
            per=fam_data.per,
            description=fam_data.description,
            dimensions=fam_data.dimensions,
            units=units,
        )
    return families


_FAMILIES = _load_families()
TOKENS_FAMILY = _FAMILIES['tokens']
_ALL_UNITS: dict[str, UnitDef] = {uid: unit for fam in _FAMILIES.values() for uid, unit in fam.units.items()}


def get_family(family_id: str) -> UnitFamily:
    """Look up a unit family by ID. Raises KeyError if not found."""
    return _FAMILIES[family_id]


def get_unit(unit_id: str) -> UnitDef:
    """Look up a unit definition by ID. Raises KeyError if not found."""
    return _ALL_UNITS[unit_id]
