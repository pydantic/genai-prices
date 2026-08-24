from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from ruamel.yaml import CommentedMap

from prices import source_prices, update
from prices.prices_types import ClauseEquals, ClauseOr, ModelInfo, ModelPrice

DEFAULT_MODELS = """\
  - id: model-a
    match:
      equals: model-a
    prices:
      input_mtok: 1
"""


def _model(
    model_id: str,
    *,
    match: ClauseEquals | ClauseOr | None = None,
    name: str | None = None,
    description: str | None = None,
    context_window: int | None = None,
    price: Decimal = Decimal('1'),
) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        match=match or ClauseEquals(equals=model_id),
        name=name,
        description=description,
        context_window=context_window,
        prices=ModelPrice(input_mtok=price),
    )


def _write_provider(path: Path, *, provider_id: str = 'example', models: str | None = None) -> None:
    path.write_text(
        f"""\
id: {provider_id}
name: Example
api_pattern: https://example\\.test
models:
{models or DEFAULT_MODELS}"""
    )


def test_source_prices_round_trip_and_invalid_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    source_prices_dir = tmp_path / 'source_prices'
    monkeypatch.setattr(source_prices, 'source_prices_dir', source_prices_dir)

    source_prices_dir.mkdir()
    assert source_prices.load_source_prices() == {}

    expected = {'example': {'model-a': ModelPrice(input_mtok=Decimal('2.5'))}}
    source_prices.write_source_prices('fixture', expected)

    assert source_prices.load_source_prices() == {'fixture': expected}
    assert capsys.readouterr().out == f'prices written to {source_prices_dir / "fixture.json"}\n'

    invalid_path = source_prices_dir / 'invalid.json'
    invalid_path.write_text('{"example": {"model-a": {"input_mtok": 0}}}')
    with pytest.raises(ValueError, match=f'Error loading source prices from {invalid_path}:'):
        source_prices.load_source_prices()


def test_get_providers_yaml_and_provider_validation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    providers_dir = tmp_path / 'providers'
    providers_dir.mkdir()
    _write_provider(providers_dir / 'one.yml', provider_id='one')
    _write_provider(providers_dir / 'two.yaml', provider_id='two')
    (providers_dir / 'ignored.txt').write_text('not yaml')
    monkeypatch.setattr(update, 'package_dir', tmp_path)

    assert set(update.get_providers_yaml()) == {'one', 'two'}

    invalid_path = providers_dir / 'invalid.yml'
    _write_provider(invalid_path, models='  - id: incomplete\n')
    with pytest.raises(ValueError, match=r'Invalid provider data for invalid.yml:'):
        update.ProviderYaml(invalid_path)

    invalid_id_path = providers_dir / 'invalid-id.yml'
    _write_provider(invalid_id_path, provider_id='[not-a-string]')
    with pytest.raises(AssertionError, match='Provider ID must be a string'):
        update.ProviderYaml(invalid_id_path)


def test_provider_yaml_update_and_save_paths(tmp_path: Path):
    path = tmp_path / 'example.yml'
    _write_provider(
        path,
        models="""\
  - id: model-a
    match:
      equals: model-a
    prices:
      input_mtok: 1
  - id: model-b
    match:
      equals: model-b
    prices:
      - prices:
          input_mtok: 1
""",
    )
    provider = update.ProviderYaml(path)

    alias = ClauseEquals(equals='model-a-alias')
    replacement = _model(
        'model-a',
        match=alias,
        name='Model A',
        description='A description',
        context_window=128,
        price=Decimal('2'),
    )
    provider.update_model('model-a', replacement, set_prices=True)
    existing_aliases = ClauseOr(or_=[ClauseEquals(equals='model-a'), alias])  # pyright: ignore[reportCallIssue]
    provider.update_model('model-a', _model('model-a', match=existing_aliases))

    aliases = ClauseOr(or_=[alias, ClauseEquals(equals='model-a-alias-2')])  # pyright: ignore[reportCallIssue]
    provider.update_model('model-a', _model('model-a', match=aliases))
    provider.update_model('model-a', _model('model-a', match=alias))
    provider.update_model('model-a', _model('model-a', match=ClauseEquals(equals='model-a-alias-3')))
    provider.add_id_to_model('model-a', 'model-a-alias-4')
    provider.update_model('model-b', _model('model-b', match=ClauseEquals(equals='model-b-alias')), set_prices=True)

    discrepancy = ModelPrice(input_mtok=Decimal('3'))
    provider.set_price_discrepency('model-a', 'first', discrepancy)
    provider.set_price_discrepency('model-a', 'second', discrepancy)

    extra = _model('extra-model', description='  Extra description  ')
    assert provider.add_model(extra) == 1
    assert provider.add_model(extra) == 0
    provider.add_price('price-only', ModelPrice(input_mtok=Decimal('4')))
    provider.remove_model('model-b')
    with pytest.raises(LookupError, match="Model with ID 'missing' not found"):
        provider._get_model('missing')

    provider.save()

    saved = update.ProviderYaml(path)
    assert [model.id for model in saved.provider.models] == ['extra-model', 'model-a', 'price-only']
    model_a = saved._get_model('model-a')
    assert model_a['prices'] == {'input_mtok': 2}
    saved_model_a = saved.provider.find_model('model-a')
    assert saved_model_a is not None
    assert set(saved_model_a.price_discrepancies or {}) == {'first', 'second'}
    assert 'description: >-' in path.read_text()

    no_removals_path = tmp_path / 'no-removals.yml'
    _write_provider(no_removals_path)
    update.ProviderYaml(no_removals_path).save()


def test_get_provider_yaml_string_sorts_and_formats_models():
    data: update.ProviderYamlDict = {
        'id': 'example',
        'models': [
            CommentedMap(id='z-model', match=CommentedMap(equals='z-model'), prices=CommentedMap(input_mtok=1)),
            CommentedMap(id='a-model', match=CommentedMap(equals='a-model'), prices=CommentedMap(input_mtok=1)),
        ],
    }

    yaml_data = update.get_provider_yaml_string(data)

    assert yaml_data.index('id: a-model') < yaml_data.index('id: z-model')
    assert '\n\n  - id: z-model' in yaml_data
