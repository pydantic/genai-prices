from __future__ import annotations

import json
import runpy
import subprocess
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CURRENT_DATA = cast(dict[str, object], json.loads((REPO_ROOT / 'prices/data_v2.json').read_bytes()))
CURRENT_SCHEMA_BYTES = (REPO_ROOT / 'prices/data_v2.schema.json').read_bytes()
CURRENT_UNITS_SOURCE = (REPO_ROOT / 'prices/units.yml').read_text()
check_v2_compatibility = cast(
    Callable[[str, Path], str],
    runpy.run_path(str(REPO_ROOT / '.github/scripts/check_v2_compatibility.py'))['check_v2_compatibility'],
)


def test_v2_compatibility_bootstraps_from_provider_array(tmp_path: Path) -> None:
    base_oid = _create_repo(tmp_path, [])

    assert check_v2_compatibility(base_oid, tmp_path) == base_oid


def test_v2_compatibility_accepts_unchanged_deployed_contract(tmp_path: Path) -> None:
    base_oid = _create_repo(tmp_path, CURRENT_DATA)

    assert check_v2_compatibility(base_oid, tmp_path) == base_oid


def test_v2_compatibility_rejects_schema_byte_change(tmp_path: Path) -> None:
    base_oid = _create_repo(tmp_path, CURRENT_DATA)
    (tmp_path / 'prices/data_v2.schema.json').write_bytes(CURRENT_SCHEMA_BYTES + b' ')

    with pytest.raises(ValueError, match='Published v2 schema changed'):
        check_v2_compatibility(base_oid, tmp_path)


def test_v2_compatibility_rejects_removed_unit(tmp_path: Path) -> None:
    base_oid = _create_repo(tmp_path, CURRENT_DATA)
    candidate = deepcopy(CURRENT_DATA)
    units = cast(dict[str, object], candidate['units'])
    del units['input_tokens']
    _write_json(tmp_path / 'prices/data_v2.json', candidate)

    with pytest.raises(ValueError, match='Published unit removed: input_tokens'):
        check_v2_compatibility(base_oid, tmp_path)


def test_v2_compatibility_rejects_new_provider_structure(tmp_path: Path) -> None:
    base_oid = _create_repo(tmp_path, CURRENT_DATA)
    candidate = deepcopy(CURRENT_DATA)
    providers = cast(list[dict[str, object]], candidate['providers'])
    providers[0]['future_field'] = True
    _write_json(tmp_path / 'prices/data_v2.json', candidate)

    with pytest.raises(ValueError, match='does not match the deployed v2 schema'):
        check_v2_compatibility(base_oid, tmp_path)


def _create_repo(path: Path, base_data: object) -> str:
    prices_dir = path / 'prices'
    prices_dir.mkdir()
    _write_json(prices_dir / 'data_v2.json', base_data)
    (prices_dir / 'data_v2.schema.json').write_bytes(CURRENT_SCHEMA_BYTES)
    (prices_dir / 'units.yml').write_text(CURRENT_UNITS_SOURCE)
    subprocess.run(['git', 'init', '--quiet'], cwd=path, check=True)
    subprocess.run(['git', 'config', 'user.email', 'tests@example.com'], cwd=path, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Tests'], cwd=path, check=True)
    subprocess.run(['git', 'add', 'prices'], cwd=path, check=True)
    subprocess.run(['git', 'commit', '--quiet', '-m', 'base'], cwd=path, check=True)
    base_oid = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=path,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()

    _write_json(prices_dir / 'data_v2.json', CURRENT_DATA)
    (prices_dir / 'data_v2.schema.json').write_bytes(CURRENT_SCHEMA_BYTES)
    return base_oid


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + '\n')
