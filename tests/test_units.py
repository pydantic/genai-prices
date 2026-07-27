import ast
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from genai_prices.data_units import unit_data
from genai_prices.types import ModelPrice
from genai_prices.units import UnitRegistry, _get_registry
from prices import package_data, prices_types as build_types
from prices.build import load_units
from prices.export_validation import validate_units


def _build_provider_prices(
    prices: build_types.ModelPrice | list[build_types.ConditionalPrice],
    *,
    extractors: list[build_types.UsageExtractor] | None = None,
    model_id: str = 'model',
) -> build_types.Provider:
    return build_types.Provider(
        id='testing',
        name='Testing',
        api_pattern='testing',
        extractors=extractors,
        models=[
            build_types.ModelInfo(
                id=model_id,
                match=build_types.ClauseEquals(equals=model_id),
                prices=prices,
            )
        ],
    )


def _build_extractor(dest: str) -> build_types.UsageExtractor:
    return build_types.UsageExtractor.model_construct(
        root='usage',
        mappings=[_build_extractor_mapping('value', dest)],
        api_flavor='default',
        model_path='model',
    )


def _build_extractor_mapping(path: str, dest: str, *, required: bool = True) -> build_types.UsageExtractorMapping:
    return build_types.UsageExtractorMapping.model_construct(path=path, dest=dest, required=required)


def test_units_yml_defines_pre_expansion_registry() -> None:
    units = load_units()

    assert len(units) == 21
    assert set(units) >= {
        'input_tokens',
        'output_tokens',
        'cache_read_tokens',
        'cache_write_tokens',
        'input_text_tokens',
        'output_text_tokens',
        'input_audio_tokens',
        'output_audio_tokens',
        'input_image_tokens',
        'output_image_tokens',
        'input_video_tokens',
        'output_video_tokens',
        'requests',
    }


def test_generated_unit_modules_are_separate_from_provider_data() -> None:
    python_provider_data = Path('packages/python/genai_prices/data.py').read_text()
    python_unit_data = Path('packages/python/genai_prices/data_units.py').read_text()
    typescript_provider_data = Path('packages/js/src/data.ts').read_text()
    typescript_unit_data = Path('packages/js/src/dataUnits.ts').read_text()

    assert 'unit_data' not in python_provider_data
    assert 'unitData' not in typescript_provider_data
    assert ast.literal_eval(python_unit_data.split('unit_data: dict[str, Any] = ', 1)[1]) == load_units()
    assert all(usage_key in typescript_unit_data for usage_key in load_units())


def test_generated_unit_modules_contain_only_raw_data_types() -> None:
    assert 'UnitRegistry' not in Path('packages/python/genai_prices/data_units.py').read_text()
    assert 'UnitRegistry' not in Path('packages/js/src/dataUnits.ts').read_text()


def test_unit_registry_indexes_bundled_units() -> None:
    registry = UnitRegistry(unit_data)

    assert set(registry.units) == set(unit_data)
    assert registry.unit_for_price_key('input_mtok') is registry.units['input_tokens']
    assert registry.ancestor_usage_keys('cache_audio_read_tokens') == frozenset(
        {'input_tokens', 'cache_read_tokens', 'input_audio_tokens'}
    )
    assert (
        registry.find_join(registry.units['cache_read_tokens'], registry.units['input_audio_tokens'])
        is registry.units['cache_audio_read_tokens']
    )
    assert registry.find_join(registry.units['input_tokens'], registry.units['output_tokens']) is None


def test_unit_registry_units_mapping_is_immutable() -> None:
    registry = UnitRegistry(unit_data)

    with pytest.raises(TypeError, match="'mappingproxy' object does not support item assignment"):
        cast(dict[str, Any], registry.units)['new_unit'] = registry.units['input_tokens']


@pytest.mark.parametrize(
    ('usage_key', 'price_key', 'message'),
    [
        ('_private_name', 'private_mtok', 'must not start'),
        ('$input_tokens', 'input_mtok', 'is not a public identifier'),
        ('class', 'class_mtok', 'is a reserved keyword'),
        ('valid_usage', 'function', 'is a reserved keyword'),
    ],
)
def test_validate_units_rejects_unsafe_public_keys(usage_key: str, price_key: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_units(
            {
                usage_key: {
                    'per': 1_000_000,
                    'price_key': price_key,
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
            }
        )


def test_validate_units_rejects_duplicate_price_keys_and_dimensions() -> None:
    with pytest.raises(ValueError, match='Duplicate unit price key: input_mtok'):
        validate_units(
            {
                'input_tokens': {
                    'per': 1_000_000,
                    'price_key': 'input_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
                'input_audio_tokens': {
                    'per': 1_000_000,
                    'price_key': 'input_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input', 'modality': 'audio'},
                },
            }
        )

    with pytest.raises(ValueError, match='Duplicate unit dimensions: input_tokens and prompt_tokens'):
        validate_units(
            {
                'input_tokens': {
                    'per': 1_000_000,
                    'price_key': 'input_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
                'prompt_tokens': {
                    'per': 1_000_000,
                    'price_key': 'prompt_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
            }
        )


def test_validate_units_rejects_open_intervals_and_missing_joins() -> None:
    with pytest.raises(ValueError, match='Missing intermediate unit dimensions'):
        validate_units(
            {
                'input_tokens': {
                    'per': 1_000_000,
                    'price_key': 'input_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
                'cache_read_tokens': {
                    'per': 1_000_000,
                    'price_key': 'cache_read_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input', 'cache': 'read'},
                },
                'cache_video_read_tokens': {
                    'per': 1_000_000,
                    'price_key': 'cache_video_read_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input', 'modality': 'video', 'cache': 'read'},
                },
            }
        )

    with pytest.raises(ValueError, match='Missing join unit dimensions'):
        validate_units(
            {
                'input_tokens': {
                    'per': 1_000_000,
                    'price_key': 'input_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input'},
                },
                'cache_write_tokens': {
                    'per': 1_000_000,
                    'price_key': 'cache_write_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input', 'cache': 'write'},
                },
                'input_audio_tokens': {
                    'per': 1_000_000,
                    'price_key': 'input_audio_mtok',
                    'dimensions': {'family': 'tokens', 'direction': 'input', 'modality': 'audio'},
                },
            }
        )


def test_model_price_str_includes_unregistered_candidate_keys() -> None:
    assert str(ModelPrice(hovercraft_mtok=Decimal('1'))) == '$1/hovercraft MTok'


def test_package_python_data_accepts_separated_inputs_without_units_yml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from genai_prices import types as runtime_types

    units = {
        'transient_tokens': {
            'per': 1_000_000,
            'price_key': 'transient_mtok',
            'dimensions': {'family': 'transient'},
        },
    }
    provider = _build_provider_prices(
        build_types.ModelPrice.model_validate({'transient_mtok': '1'}),
        extractors=[_build_extractor('transient_tokens')],
    )
    provider_data = build_types.providers_schema.dump_python(
        [provider],
        mode='json',
        by_alias=True,
        exclude_none=True,
        warnings=False,
    )

    py_package_dir = tmp_path / 'genai_prices'
    py_package_dir.mkdir()
    monkeypatch.setattr(runtime_types, '__file__', str(py_package_dir / 'types.py'))
    monkeypatch.setattr(package_data, 'root_dir', tmp_path)

    def skip_format_generated_python_data(_path: Path, *, post_process_provider_reprs: bool = False) -> None:
        _ = post_process_provider_reprs

    monkeypatch.setattr(package_data, '_format_generated_python_data', skip_format_generated_python_data)

    package_data.package_python_data(provider_data, units)

    assert (py_package_dir / 'data.py').exists()
    unit_data_content = (py_package_dir / 'data_units.py').read_text()
    generated_units = ast.literal_eval(unit_data_content.split('unit_data: dict[str, Any] = ', 1)[1])
    assert generated_units == units


def test_runtime_provider_registry_injection_preserves_malformed_shapes_for_schema_validation() -> None:
    from genai_prices import types as runtime_types

    registry = UnitRegistry({})
    invalid_provider = object()
    invalid_extractor = object()
    raw_providers: list[Any] = [
        invalid_provider,
        {'id': 'without-extractors'},
        {'id': 'with-extractors', 'extractors': [invalid_extractor, {'mappings': []}]},
    ]

    assert runtime_types._inject_extractor_registry({}, registry) == {}
    injected = runtime_types._inject_extractor_registry(raw_providers, registry)
    assert injected[0] is invalid_provider
    assert injected[1] == {'id': 'without-extractors'}
    assert injected[2]['extractors'][0] is invalid_extractor
    assert injected[2]['extractors'][1] == {'mappings': [], '_registry': registry}


def test_package_python_data_preserves_bundled_registry_if_runtime_provider_validation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from genai_prices import types as runtime_types

    class RuntimeProviderValidationError(RuntimeError):
        pass

    bundled_registry = _get_registry()
    units = {
        'transient_tokens': {
            'per': 1_000_000,
            'price_key': 'transient_mtok',
            'dimensions': {'family': 'transient'},
        },
    }
    py_package_dir = tmp_path / 'genai_prices'
    py_package_dir.mkdir()
    monkeypatch.setattr(runtime_types, '__file__', str(py_package_dir / 'types.py'))

    def fail_runtime_provider_validation(_provider_data: Any, _registry: UnitRegistry) -> list[runtime_types.Provider]:
        raise RuntimeProviderValidationError('sentinel runtime provider validation failure')

    monkeypatch.setattr(runtime_types, '_providers_from_raw', fail_runtime_provider_validation)

    with pytest.raises(RuntimeProviderValidationError, match='sentinel runtime provider validation failure'):
        package_data.package_python_data([], units)

    assert _get_registry() is bundled_registry
    assert 'transient_tokens' not in bundled_registry.units
