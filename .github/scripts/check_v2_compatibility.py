"""Validate a candidate v2 publication against the exact pull-request base."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from jsonschema.validators import validator_for
from ruamel.yaml import YAML

from genai_prices.units import UnitRegistry
from prices.export_validation import validate_export_payload, validate_unit_evolution
from prices.prices_types import providers_schema

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = Path('prices/data_v2.json')
SCHEMA_PATH = Path('prices/data_v2.schema.json')
UNITS_SOURCE_PATH = Path('prices/units.yml')


def check_v2_compatibility(base_ref: str, repo_root: Path = REPO_ROOT) -> str:
    """Check the working-tree v2 artifact against ``base_ref`` and return its exact commit ID."""
    base_oid = _resolve_commit(base_ref, repo_root)
    candidate_data = _read_json(repo_root / DATA_PATH, source='candidate v2 data')
    candidate_schema_bytes = (repo_root / SCHEMA_PATH).read_bytes()
    candidate_schema = _load_schema(candidate_schema_bytes, source='candidate v2 schema')

    base_data = _load_json_bytes(
        _read_from_ref(base_oid, DATA_PATH, repo_root),
        source=f'base v2 data at {base_oid}',
    )
    if isinstance(base_data, list):
        previous_units = _load_bootstrap_units(base_oid, repo_root)
        validation_schema = candidate_schema
        print(f'Bootstrapping wrapped v2 compatibility from provider-array base {base_oid}.')
    else:
        base_wrapper = _wrapper(base_data, source=f'base v2 data at {base_oid}')
        base_schema_bytes = _read_from_ref(base_oid, SCHEMA_PATH, repo_root)
        if candidate_schema_bytes != base_schema_bytes:
            raise ValueError(f'Published v2 schema changed relative to base commit {base_oid}')

        validation_schema = _load_schema(base_schema_bytes, source=f'base v2 schema at {base_oid}')
        _validate_json_schema(base_wrapper, validation_schema, source=f'base v2 data at {base_oid}')
        previous_units = _units(base_wrapper, source=f'base v2 data at {base_oid}')

    candidate_wrapper = _wrapper(candidate_data, source='candidate v2 data')
    _validate_json_schema(candidate_wrapper, validation_schema, source='candidate v2 data')
    candidate_units = _units(candidate_wrapper, source='candidate v2 data')
    validate_unit_evolution(previous_units, candidate_units)

    raw_providers = candidate_wrapper['providers']
    providers = providers_schema.validate_python(raw_providers)
    source_units = _load_units_yaml((repo_root / UNITS_SOURCE_PATH).read_text(), source='candidate unit source')
    source_registry = validate_export_payload(providers, source_units)
    UnitRegistry.from_untrusted(candidate_units)
    published_projection = {
        usage_key: {
            'per': unit.per,
            'dimensions': unit.dimensions,
            **({'price_key': unit.price_key} if unit.price_key != usage_key else {}),
        }
        for usage_key, unit in source_registry.units.items()
    }
    if candidate_units != published_projection:
        raise ValueError('Candidate v2 units do not match the validated prices/units.yml runtime projection')

    print(f'V2 compatibility passed against exact base commit {base_oid}.')
    return base_oid


def _resolve_commit(ref: str, repo_root: Path) -> str:
    return subprocess.run(
        ['git', 'rev-parse', '--verify', f'{ref}^{{commit}}'],
        cwd=repo_root,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


def _read_from_ref(ref: str, path: Path, repo_root: Path) -> bytes:
    try:
        return subprocess.run(
            ['git', 'show', f'{ref}:{path.as_posix()}'],
            cwd=repo_root,
            capture_output=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode(errors='replace').strip()
        raise ValueError(f'Unable to read {path} from base commit {ref}: {message}') from exc


def _read_json(path: Path, *, source: str) -> object:
    try:
        return _load_json_bytes(path.read_bytes(), source=source)
    except FileNotFoundError as exc:
        raise ValueError(f'Missing {source}: {path}') from exc


def _load_json_bytes(raw: bytes, *, source: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f'Invalid JSON in {source}: {exc}') from exc


def _load_schema(raw: bytes, *, source: str) -> Mapping[str, Any]:
    schema = _load_json_bytes(raw, source=source)
    if not isinstance(schema, Mapping):
        raise ValueError(f'{source} must be a JSON object')
    typed_schema = cast(Mapping[str, Any], schema)
    validator_for(typed_schema).check_schema(typed_schema)
    return typed_schema


def _validate_json_schema(instance: object, schema: Mapping[str, Any], *, source: str) -> None:
    validator = validator_for(schema)(schema)
    if error := next(iter(validator.iter_errors(instance)), None):
        path = '.'.join(str(part) for part in error.absolute_path)
        location = f' at {path}' if path else ''
        raise ValueError(f'{source} does not match the deployed v2 schema{location}: {error.message}')


def _wrapper(raw: object, *, source: str) -> Mapping[str, object]:
    if not isinstance(raw, Mapping):
        raise ValueError(f'{source} must be a wrapped JSON object')
    return cast(Mapping[str, object], raw)


def _units(wrapper: Mapping[str, object], *, source: str) -> Mapping[str, Mapping[str, Any]]:
    raw_units = wrapper.get('units')
    if not isinstance(raw_units, Mapping):
        raise ValueError(f'{source} units must be an object')
    return cast(Mapping[str, Mapping[str, Any]], raw_units)


def _load_bootstrap_units(base_oid: str, repo_root: Path) -> Mapping[str, Mapping[str, Any]]:
    raw = _read_from_ref(base_oid, UNITS_SOURCE_PATH, repo_root).decode()
    return _load_units_yaml(raw, source=f'bootstrap unit source at {base_oid}')


def _load_units_yaml(raw: str, *, source: str) -> Mapping[str, Mapping[str, Any]]:
    units = YAML(typ='safe').load(raw)
    if not isinstance(units, Mapping):
        raise ValueError(f'{source} must be an object')
    return cast(Mapping[str, Mapping[str, Any]], units)


def main(base_ref: str) -> None:
    try:
        check_v2_compatibility(base_ref)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        sys.exit(f'::error::{exc}')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('usage: check_v2_compatibility.py <base-ref>')
    main(sys.argv[1])
