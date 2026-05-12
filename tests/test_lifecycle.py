from __future__ import annotations

import json
import subprocess
import sys

from genai_prices import data as genai_data, data_units as genai_data_units
from genai_prices.data import providers


def test_deprecated_models_present_with_flag():
    """Deprecated models should be present in built data with the deprecated flag set to True."""
    deprecated_models = [(p.id, m.id, m.deprecated) for p in providers for m in p.models if m.deprecated]
    assert len(deprecated_models) > 0, 'Expected at least one deprecated model in built data'
    for _, _, deprecated in deprecated_models:
        assert deprecated is True


def test_removed_models_absent():
    """Removed models (claude-instant-1, claude-instant-1.2) should not appear in the built provider data."""
    anthropic = next(p for p in providers if p.id == 'anthropic')
    model_ids = {m.id for m in anthropic.models}
    assert 'claude-instant-1' not in model_ids
    assert 'claude-instant-1.2' not in model_ids


def test_deprecated_flag_in_data_json():
    """The deprecated flag should appear in data.json for deprecated models and be absent for normal models."""
    from prices.utils import package_dir

    data_json_path = package_dir / 'data.json'
    data = json.loads(data_json_path.read_bytes())

    deprecated_found = False
    non_deprecated_with_flag = False

    for provider in data:
        for model in provider['models']:
            if model.get('deprecated') is True:
                deprecated_found = True
            elif 'deprecated' in model:
                non_deprecated_with_flag = True

    assert deprecated_found, 'Expected at least one model with deprecated=true in data.json'
    assert not non_deprecated_with_flag, 'Non-deprecated models should not have the deprecated key in data.json'


def test_removed_field_not_in_data_json():
    """The removed field should never appear in data.json."""
    from prices.utils import package_dir

    data_json_path = package_dir / 'data.json'
    data = json.loads(data_json_path.read_bytes())

    for provider in data:
        for model in provider['models']:
            assert 'removed' not in model, f'removed field found in data.json for model {model["id"]}'


def test_remote_payloads_remain_provider_arrays():
    """Remote JSON payloads stay provider arrays."""
    from prices.utils import package_dir

    for filename in ('data.json', 'data_slim.json'):
        payload: list[object] = json.loads((package_dir / filename).read_bytes())

        assert isinstance(payload, list)
        assert payload
        assert all(isinstance(provider, dict) for provider in payload)


def test_python_unit_data_is_separate_from_provider_data():
    """Unit registry data is bundled separately from provider-heavy Python data."""
    assert genai_data.__all__ == ('providers',)
    assert genai_data_units.__all__ == ('unit_families_data',)
    assert not hasattr(genai_data, 'unit_families_data')
    assert not hasattr(genai_data_units, 'providers')
    assert isinstance(genai_data_units.unit_families_data, dict)


def test_python_unit_data_import_does_not_import_provider_data():
    """Importing bundled unit registry data does not import the generated provider list."""
    subprocess.run(
        [
            sys.executable,
            '-c',
            "import sys; import genai_prices.data_units; assert 'genai_prices.data' not in sys.modules",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_get_registry_does_not_import_provider_data():
    """Building the active unit registry does not import the generated provider list."""
    subprocess.run(
        [
            sys.executable,
            '-c',
            (
                'import sys; '
                'from genai_prices.units import _get_registry; '
                '_get_registry(); '
                "assert 'genai_prices.data' not in sys.modules"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_generated_provider_data_import_succeeds_with_extractor_validation():
    """Generated provider data can construct extractors while destination validation is enabled."""
    subprocess.run(
        [
            sys.executable,
            '-c',
            'import genai_prices.data; assert genai_prices.data.providers',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
