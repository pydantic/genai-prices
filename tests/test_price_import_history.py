from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from prices.prices_types import ClauseEquals, ClauseOr, ModelInfo, ModelPrice
from prices.update import ProviderYaml


@pytest.mark.parametrize('direct', [True, False])
@pytest.mark.parametrize('history', ['checked-flat', 'standard', 'variant'])
def test_importers_preserve_prices_already_published_on_the_observation_date(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], direct: bool, history: str
) -> None:
    today = date.today()
    prices = (
        (
            '\n      - prices: {input_mtok: 1}\n'
            f'      - constraint: {{start_date: {today}}}\n        prices: {{input_mtok: 2}}'
        )
        if history == 'standard'
        else ' {input_mtok: 2}'
    )
    checked = f'    prices_checked: {today}\n' if history == 'checked-flat' else ''
    variant = (
        (
            f'    price_variants:\n      - when: {{processing: batch}}\n'
            f'        constraint: {{start_date: {today}}}\n        prices: {{input_mtok: 1}}\n'
        )
        if history == 'variant'
        else ''
    )
    path = tmp_path / 'provider.yml'
    path.write_text(
        'id: example\nname: Example\napi_pattern: example\nmodels:\n'
        '  - id: m\n    match: {equals: m}\n' + checked + '    prices:' + prices + '\n' + variant
    )
    provider = ProviderYaml(path)
    before = provider.provider
    new = ModelInfo(
        id='m', match=ClauseEquals(equals='m'), prices=ModelPrice(input_mtok=Decimal(3)), prices_checked=today
    )
    if direct:
        assert provider.update_model('m', new, set_prices=True) is False
        provider.save()
    else:
        assert provider.upsert_models([new], source='Example', min_count=1) == (0, 0)
    assert ProviderYaml(path).provider == before
    assert 'cannot be represented by date-only constraints; update them by hand' in capsys.readouterr().out


@pytest.mark.parametrize('direct', [True, False])
def test_held_prices_do_not_block_new_model_aliases_or_metadata(tmp_path: Path, direct: bool) -> None:
    today = date.today()
    path = tmp_path / 'provider.yml'
    path.write_text(
        'id: example\nname: Example\napi_pattern: example\nmodels:\n'
        '  - id: m\n    match: {equals: m}\n    prices: {input_mtok: 2}\n'
        f'    prices_checked: {today}\n'
    )
    provider = ProviderYaml(path)
    incoming = ModelInfo(
        id='m',
        match=ClauseOr.model_validate({'or': [{'equals': 'm'}, {'equals': 'native'}]}),
        context_window=1000,
        prices=ModelPrice(input_mtok=Decimal(3)),
        prices_checked=today,
    )
    if direct:
        assert not provider.update_model('m', incoming, set_prices=True)
        provider.save()
    else:
        assert provider.upsert_models([incoming], source='Example', min_count=1) == (0, 0)
    model = ProviderYaml(path).provider.find_model('native')
    assert model is not None and model.context_window == 1000
    assert model.prices == ModelPrice(input_mtok=Decimal(2))
    assert model.prices_checked == today
