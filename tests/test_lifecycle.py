from __future__ import annotations

import json

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
