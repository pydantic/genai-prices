import pytest

from genai_prices.units import UnitDef, get_family, get_unit


def test_unit_def_creation():
    unit = UnitDef(id='input_mtok', family_id='tokens', usage_key='input_tokens', dimensions={'direction': 'input'})
    assert unit.id == 'input_mtok'
    assert unit.usage_key == 'input_tokens'
    assert unit.dimensions == {'direction': 'input'}


def test_tokens_family_exists():
    family = get_family('tokens')
    assert family.id == 'tokens'
    assert family.per == 1_000_000


def test_get_unit():
    unit = get_unit('input_mtok')
    assert unit.family_id == 'tokens'
    assert unit.usage_key == 'input_tokens'
    assert unit.dimensions == {'direction': 'input'}


def test_get_unit_not_found():
    with pytest.raises(KeyError):
        get_unit('nonexistent')


def test_get_family_not_found():
    with pytest.raises(KeyError):
        get_family('nonexistent')


def test_tokens_family_has_22_units():
    family = get_family('tokens')
    # 2 catch-all (input, output) + 2 cache (read, write) + 4 modalities × 4 slots = 20
    assert len(family.units) == 20


def test_tokens_family_has_all_current_units():
    """All 7 currently-used units exist in the registry."""
    family = get_family('tokens')
    for unit_id in [
        'input_mtok',
        'output_mtok',
        'cache_read_mtok',
        'cache_write_mtok',
        'input_audio_mtok',
        'cache_read_audio_mtok',
        'output_audio_mtok',
    ]:
        assert unit_id in family.units, f'Missing unit: {unit_id}'


def test_tokens_family_has_new_modality_units():
    """All new modality units exist in the registry."""
    family = get_family('tokens')
    for unit_id in [
        'input_text_mtok',
        'output_text_mtok',
        'cache_read_text_mtok',
        'cache_write_text_mtok',
        'input_image_mtok',
        'output_image_mtok',
        'cache_read_image_mtok',
        'cache_write_image_mtok',
        'input_video_mtok',
        'output_video_mtok',
        'cache_read_video_mtok',
        'cache_write_video_mtok',
    ]:
        assert unit_id in family.units, f'Missing unit: {unit_id}'


def test_unit_dimensions_are_valid():
    """Every unit's dimension keys/values must be registered in its family."""
    family = get_family('tokens')
    for unit in family.units.values():
        for dim_key, dim_val in unit.dimensions.items():
            assert dim_key in family.dimensions, f'{unit.id}: unknown dimension key {dim_key}'
            assert dim_val in family.dimensions[dim_key], f'{unit.id}: invalid value {dim_val!r} for {dim_key}'


def test_catch_all_units_have_one_dimension():
    """input_mtok and output_mtok should have only the direction dimension."""
    assert get_unit('input_mtok').dimensions == {'direction': 'input'}
    assert get_unit('output_mtok').dimensions == {'direction': 'output'}


def test_cache_read_audio_usage_key():
    """cache_read_audio_mtok maps to current usage field name (not spec future name)."""
    unit = get_unit('cache_read_audio_mtok')
    assert unit.usage_key == 'cache_audio_read_tokens'
