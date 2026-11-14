from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml


@pytest.mark.parametrize('operation', ['save', 'upsert'])
def test_saved_new_models_are_not_added_again(tmp_path: Path, operation: str) -> None:
    path = tmp_path / 'provider.yml'
    path.write_text(
        'id: example\nname: Example\napi_pattern: example\nmodels:\n'
        '  - id: existing\n    match: {equals: existing}\n    prices: {input_mtok: 1}\n'
    )
    provider = ProviderYaml(path)
    model = ModelInfo(
        id='new',
        match=ClauseEquals(equals='new'),
        prices=ModelPrice(input_mtok=Decimal(2)),
        prices_checked=date(2026, 1, 2),
    )
    if operation == 'save':
        provider.add_model(model)
        provider.save()
        first = path.read_text()
        provider.save()
    else:
        assert provider.upsert_models([model], source='Example', min_count=1) == (1, 0)
        first = path.read_text()
        assert provider.upsert_models([model], source='Example', min_count=1) == (0, 1)

    assert path.read_text() == first
    assert [record.id for record in ProviderYaml(path).provider.models] == ['existing', 'new']


def test_saved_new_model_can_receive_a_later_price_update(tmp_path: Path) -> None:
    path = tmp_path / 'provider.yml'
    path.write_text('id: example\nname: Example\napi_pattern: example\nmodels: []\n')
    provider = ProviderYaml(path)
    model = ModelInfo(
        id='new',
        match=ClauseEquals(equals='new'),
        prices=ModelPrice(input_mtok=Decimal(2)),
        prices_checked=date(2026, 1, 2),
    )
    assert provider.upsert_models([model], source='Example', min_count=1) == (1, 0)
    later = model.model_copy(update={'prices': ModelPrice(input_mtok=Decimal(3)), 'prices_checked': date(2026, 1, 3)})
    assert provider.upsert_models([later], source='Example', min_count=1) == (0, 1)
    [saved] = ProviderYaml(path).provider.models
    assert isinstance(saved.prices, list)
    assert [entry.prices.input_mtok for entry in saved.prices] == [Decimal(2), Decimal(3)]


def test_saved_removal_does_not_remove_a_later_readdition(tmp_path: Path) -> None:
    path = tmp_path / 'provider.yml'
    path.write_text(
        'id: example\nname: Example\napi_pattern: example\nmodels:\n'
        '  - id: existing\n    match: {equals: existing}\n    prices: {input_mtok: 1}\n'
    )
    provider = ProviderYaml(path)
    provider.remove_model('existing')
    provider.save()
    model = ModelInfo(id='existing', match=ClauseEquals(equals='existing'), prices=ModelPrice(input_mtok=Decimal(2)))
    provider.add_model(model)
    provider.save()
    provider.save()
    assert [record.id for record in ProviderYaml(path).provider.models] == ['existing']
