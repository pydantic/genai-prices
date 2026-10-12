from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from prices.schema_compatibility import is_v2_schema_compatible, main

BASELINE: dict[str, Any] = {
    '$defs': {
        'ModelInfo': {'properties': {'prices': {'$ref': '#/$defs/ModelPrice'}}, 'required': ['prices']},
        'ModelPrice': {'properties': {'input_mtok': {'type': 'number'}}},
    }
}


def test_optional_price_variants_preserve_the_legacy_schema() -> None:
    candidate = deepcopy(BASELINE)
    candidate['$defs']['ModelInfo']['properties']['price_variants'] = {'type': 'array'}
    assert is_v2_schema_compatible(BASELINE, candidate)
    candidate['$defs']['PriceVariant'] = {'properties': {'prices': {'$ref': '#/$defs/ModelPrice'}}}
    assert is_v2_schema_compatible(BASELINE, candidate)
    assert is_v2_schema_compatible(candidate, candidate)
    assert 'PriceVariant' in candidate['$defs']
    candidate['$defs']['ModelInfo']['required'].append('price_variants')
    assert not is_v2_schema_compatible(BASELINE, candidate)


@pytest.mark.parametrize(
    'change', ['new-unit', 'changed-unit', 'other-field', 'existing-variant', 'existing-definition']
)
def test_other_schema_changes_are_rejected(change: str) -> None:
    baseline = BASELINE
    candidate = deepcopy(BASELINE)
    if change == 'new-unit':
        candidate['$defs']['ModelPrice']['properties']['new_mtok'] = {'type': 'number'}
    elif change == 'changed-unit':
        candidate['$defs']['ModelPrice']['properties']['input_mtok']['type'] = 'string'
    elif change == 'other-field':
        candidate['$defs']['ModelInfo']['properties']['other_field'] = {'type': 'string'}
    elif change == 'existing-variant':
        candidate['$defs']['ModelInfo']['properties']['price_variants'] = {'type': 'array'}
        baseline = deepcopy(candidate)
        candidate['$defs']['ModelInfo']['properties']['price_variants']['type'] = 'string'
    else:
        candidate['$defs']['ModelInfo']['properties']['price_variants'] = {'$ref': '#/$defs/PriceVariant'}
        candidate['$defs']['PriceVariant'] = {'type': 'object'}
        baseline = deepcopy(candidate)
        candidate['$defs']['PriceVariant']['type'] = 'string'
    assert not is_v2_schema_compatible(baseline, candidate)


@pytest.mark.parametrize('compatible', [True, False])
def test_schema_compatibility_cli(
    compatible: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(['git', 'init', '--quiet', str(tmp_path)], check=True)
    schema = tmp_path / 'schema.json'
    schema.write_text(json.dumps(BASELINE))
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'schema.json'], check=True)
    subprocess.run(
        [
            'git',
            '-C',
            str(tmp_path),
            '-c',
            'user.name=Schema Test',
            '-c',
            'user.email=test@example.invalid',
            '-c',
            'commit.gpgsign=false',
            'commit',
            '--quiet',
            '-m',
            'Add baseline schema',
        ],
        check=True,
    )
    candidate = deepcopy(BASELINE)
    candidate['$defs']['ModelInfo']['properties']['price_variants'] = {'type': 'array'}
    if not compatible:
        candidate['$defs']['ModelPrice']['properties']['new_mtok'] = {'type': 'number'}
    schema.write_text(json.dumps(candidate))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['check-schema', '--base', 'HEAD', 'schema.json'])
    if compatible:
        main()
    else:
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2
        assert 'the existing v2 schema changed' in capsys.readouterr().err
