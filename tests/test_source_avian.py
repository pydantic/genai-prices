from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_avian
from prices.prices_types import ModelPrice, StartDateConstraint
from prices.update import ProviderYaml
from prices.utils import package_dir

FLASH = {
    'id': 'deepseek/deepseek-v4-flash',
    'display_name': 'DeepSeek V4 Flash',
    'context_length': 1000000,
    'pricing': {'input_per_million': 0.14, 'output_per_million': 0.28, 'cache_read_per_million': 0.0028},
}


def test_avian_parses_per_million_prices_and_skips_unpriced_models() -> None:
    models = source_avian.parse_models([FLASH, {'id': 'unpriced', 'pricing': {}}])

    assert [(model.id, model.name, model.context_window) for model in models] == [
        ('deepseek/deepseek-v4-flash', 'DeepSeek V4 Flash', 1000000)
    ]
    assert models[0].prices == ModelPrice(
        input_mtok=Decimal('0.14'), cache_read_mtok=Decimal('0.0028'), output_mtok=Decimal('0.28')
    )


def test_avian_adds_new_models_and_appends_a_dated_price_keeping_unreported_keys(tmp_path: Path) -> None:
    provider_path = tmp_path / 'avian.yml'
    provider_path.write_text(
        """\
id: avian
name: Avian
api_pattern: avian
models:
  - id: deepseek/deepseek-v4-flash
    match: {equals: deepseek/deepseek-v4-flash}
    prices: {input_mtok: 0.0805, cache_read_mtok: 0.0165, output_mtok: 0.161, web_searches_kcount: 5}
"""
    )

    new_model = {'id': 'new/model', 'pricing': {'input_per_million': 1, 'output_per_million': 2}}
    assert ProviderYaml(provider_path).upsert_models(
        source_avian.parse_models([FLASH, new_model]), source='Avian', min_count=1
    ) == (1, 1)

    model = ProviderYaml(provider_path).provider.find_model('deepseek/deepseek-v4-flash')
    assert model is not None
    assert isinstance(model.prices, list)
    assert model.prices[0].constraint is None
    assert model.prices[0].prices == ModelPrice.model_validate(
        {'input_mtok': '0.0805', 'cache_read_mtok': '0.0165', 'output_mtok': '0.161', 'web_searches_kcount': '5'}
    )
    assert model.prices[1].constraint == StartDateConstraint(start_date=date.today())
    assert model.prices[1].prices == ModelPrice.model_validate(
        {'input_mtok': '0.14', 'cache_read_mtok': '0.0028', 'output_mtok': '0.28', 'web_searches_kcount': '5'}
    )
    new = ProviderYaml(provider_path).provider.find_model('new/model')
    assert new is not None
    assert new.prices == ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2'))
    assert '&id' not in provider_path.read_text()


def test_avian_refuses_a_suspiciously_small_catalog(tmp_path: Path) -> None:
    provider_path = tmp_path / 'avian.yml'
    copyfile(package_dir / 'providers/avian.yml', provider_path)

    with pytest.raises(RuntimeError, match='Avian returned only 0 priced models; expected at least 10'):
        ProviderYaml(provider_path).upsert_models([], source='Avian', min_count=source_avian.MIN_MODEL_COUNT)


@pytest.mark.vcr()
def test_avian_main_fetches_recorded_models(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'avian.yml'
    copyfile(package_dir / 'providers/avian.yml', provider_path)

    source_avian.main(provider_path)

    assert capsys.readouterr().out == 'Avian prices updated: 0 added, 19 updated\n'
