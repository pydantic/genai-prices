import genai_prices
from genai_prices.units import UnitDef, UnitFamily, UnitRegistry


def test_unit_registry_classes_are_not_top_level_exports() -> None:
    assert 'UnitDef' not in genai_prices.__all__
    assert 'UnitFamily' not in genai_prices.__all__
    assert 'UnitRegistry' not in genai_prices.__all__
    assert not hasattr(genai_prices, 'UnitDef')
    assert not hasattr(genai_prices, 'UnitFamily')
    assert not hasattr(genai_prices, 'UnitRegistry')


def test_unit_registry_classes_are_importable_from_units_module() -> None:
    assert UnitDef.__name__ == 'UnitDef'
    assert UnitFamily.__name__ == 'UnitFamily'
    assert UnitRegistry.__name__ == 'UnitRegistry'
