from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest
from pydantic import ValidationError

from prices import source_gonkabroker
from prices.prices_types import ModelPrice, StartDateConstraint
from prices.update import ProviderYaml
from prices.utils import package_dir
from prices.write_guard import ALLOW_MODEL_COUNT_DROP_ENV


def catalog_model(
    model_id: str, prompt: str, *, cache_read: str | None = None, output_modalities: list[str] | None = None
) -> dict[str, object]:
    return {
        'id': model_id,
        'name': model_id.split('/')[-1],
        'context_length': 400_000,
        'max_output_length': 16_384,
        'output_modalities': output_modalities or ['text'],
        'pricing': {
            'prompt': prompt,
            'completion': prompt,
            'input': float(prompt) * 1_000_000,
            'output': float(prompt) * 1_000_000,
            'input_cache_read': cache_read or prompt,
        },
    }


CATALOG = json.dumps(
    {
        'object': 'list',
        'data': [
            catalog_model('zai-org/GLM-5.3-Flash', '0.0000002'),
            catalog_model('MiniMaxAI/MiniMax-M2.7', '0.00000025', cache_read='0.00000005'),
            catalog_model('BAAI/bge-m3', '0.00000001', output_modalities=['embeddings']),
        ],
    }
).encode()


def write_provider(path: Path, models: str = ' []') -> None:
    path.write_text(f'id: gonkabroker\nname: Gonka Broker\napi_pattern: gonkabroker\nmodels:{models}\n')


def test_parse_catalog_converts_per_token_rates() -> None:
    models = source_gonkabroker.parse_catalog(CATALOG)

    assert [model.id for model in models] == ['zai-org/GLM-5.3-Flash', 'MiniMaxAI/MiniMax-M2.7', 'BAAI/bge-m3']
    assert models[0].name == 'GLM-5.3-Flash'
    assert models[0].context_window == 400_000
    assert models[1].prices == ModelPrice(
        input_mtok=Decimal('0.25'), cache_read_mtok=Decimal('0.05'), output_mtok=Decimal('0.25')
    )
    assert all(model.prices_checked == date.today() for model in models)


def test_parse_catalog_omits_a_cache_read_rate_equal_to_input() -> None:
    model = source_gonkabroker.parse_catalog(CATALOG)[0]

    assert model.prices == ModelPrice(input_mtok=Decimal('0.2'), output_mtok=Decimal('0.2'))


def test_parse_catalog_prices_embeddings_on_input_only() -> None:
    embeddings = source_gonkabroker.parse_catalog(CATALOG)[2]

    assert embeddings.prices == ModelPrice(input_mtok=Decimal('0.01'))


def test_parse_catalog_rejects_duplicate_models() -> None:
    catalog = json.dumps({'data': [catalog_model('a/b', '0.0000002'), catalog_model('a/b', '0.0000003')]}).encode()

    with pytest.raises(RuntimeError, match='Duplicate Gonka Broker model in catalog: a/b'):
        source_gonkabroker.parse_catalog(catalog)


def test_parse_catalog_rejects_changed_shape() -> None:
    model = catalog_model('a/b', '0.0000002')
    model['pricing'] = {'input': 0.2, 'output': 0.2}

    with pytest.raises(ValidationError):
        source_gonkabroker.parse_catalog(json.dumps({'data': [model]}).encode())


def test_updater_preserves_metadata_and_price_history(tmp_path: Path) -> None:
    provider_path = tmp_path / 'gonkabroker.yml'
    write_provider(
        provider_path,
        """
  - id: zai-org/GLM-5.3-Flash
    name: Curated name
    match: {equals: zai-org/GLM-5.3-Flash}
    context_window: 123456
    deprecated: true
    price_discrepancies: {source: old}
    prices: {input_mtok: 0.3, output_mtok: 0.3}""",
    )
    model = source_gonkabroker.parse_catalog(CATALOG)[0]

    assert source_gonkabroker.update_gonkabroker_provider(ProviderYaml(provider_path), [model]) == (0, 1)

    updated = ProviderYaml(provider_path).provider.find_model('zai-org/GLM-5.3-Flash')
    assert updated is not None
    assert updated.name == 'Curated name'
    assert updated.context_window == 123456
    assert updated.deprecated is True
    assert updated.price_discrepancies is None
    assert isinstance(updated.prices, list)
    assert updated.prices[0].prices == ModelPrice(input_mtok=Decimal('0.3'), output_mtok=Decimal('0.3'))
    assert isinstance(updated.prices[-1].constraint, StartDateConstraint)
    assert updated.prices[-1].constraint.start_date == date.today()
    assert updated.prices[-1].prices == model.prices

    source_gonkabroker.update_gonkabroker_provider(ProviderYaml(provider_path), [model])

    rerun = ProviderYaml(provider_path).provider.find_model('zai-org/GLM-5.3-Flash')
    assert rerun is not None
    assert isinstance(rerun.prices, list)
    assert len(rerun.prices) == 2


def test_updater_adds_models(tmp_path: Path) -> None:
    provider_path = tmp_path / 'gonkabroker.yml'
    write_provider(provider_path)
    models = source_gonkabroker.parse_catalog(CATALOG)

    assert source_gonkabroker.update_gonkabroker_provider(ProviderYaml(provider_path), models) == (3, 0)
    assert [model.id for model in ProviderYaml(provider_path).provider.models] == [
        'BAAI/bge-m3',
        'MiniMaxAI/MiniMax-M2.7',
        'zai-org/GLM-5.3-Flash',
    ]


@pytest.mark.parametrize('new_count', [0, 1])
def test_updater_refuses_a_catalog_below_half_the_tracked_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_count: int
) -> None:
    monkeypatch.delenv(ALLOW_MODEL_COUNT_DROP_ENV, raising=False)
    provider_path = tmp_path / 'gonkabroker.yml'
    write_provider(
        provider_path,
        ''.join(
            f'\n  - id: model-{index}\n    match: {{equals: model-{index}}}\n    prices: {{input_mtok: 1}}'
            for index in range(4)
        ),
    )
    before = provider_path.read_text()
    models = source_gonkabroker.parse_catalog(CATALOG)[:new_count]

    with pytest.raises(SystemExit, match='refusing to write'):
        source_gonkabroker.update_gonkabroker_provider(ProviderYaml(provider_path), models)
    assert provider_path.read_text() == before


@pytest.mark.vcr()
def test_main_fetches_recorded_catalog(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'gonkabroker.yml'
    copyfile(package_dir / 'providers/gonkabroker.yml', provider_path)

    source_gonkabroker.main(provider_path)

    assert capsys.readouterr().out == 'Gonka Broker prices updated: 0 added, 4 updated\n'
