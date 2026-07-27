import ast
from pathlib import Path

from prices.build import load_units


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
