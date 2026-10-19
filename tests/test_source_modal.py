from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from shutil import copyfile
from typing import Any

import pytest

from prices import source_modal
from prices.prices_types import ModelPrice
from prices.utils import package_dir


def svelte_data(values: list[Any]) -> dict[str, Any]:
    return {'type': 'data', 'nodes': [{'type': 'data', 'data': [{}]}, {'type': 'data', 'data': values}]}


def model_page(rates: dict[str, str] | None, *, shared: bool = True) -> dict[str, Any]:
    values: list[Any] = [
        {'model': 1},
        {'baseModelRepoId': 2, 'displayName': 3, 'hasSharedEndpoint': 4, 'tokenRates': 5 if rates else -1},
        'moonshotai/Kimi-K3',
        'Kimi K3',
        shared,
    ]
    if rates:
        values.append({key: 6 + index for index, key in enumerate(rates)})
        values.extend(rates.values())
    return svelte_data(values)


RATES = {'promptMtok': '3.00', 'cachedPromptMtok': '0.30', 'completionMtok': '15.00', 'reasoningMtok': ''}


def test_modal_library_lists_model_pages() -> None:
    data = svelte_data([{'models': 1}, [2], {'name': 3, 'href': 4}, 'Kimi K3', '/library/moonshot/kimi-k3'])

    assert source_modal.parse_library_data(data) == ['/library/moonshot/kimi-k3']


@pytest.mark.parametrize(
    ('data', 'error'),
    [
        (svelte_data([{'title': 1}, 'Model Library']), 'Modal library page has no models'),
        (svelte_data([{'models': 1}, [2], {'href': 3}, 'https://example.com']), 'Unexpected Modal library model links'),
    ],
)
def test_modal_rejects_an_unexpected_library(data: dict[str, Any], error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_modal.parse_library_data(data)


def test_modal_shared_endpoint_token_rates() -> None:
    model = source_modal.parse_model_data(model_page(RATES))

    assert model is not None
    assert (model.id, model.name) == ('moonshotai/Kimi-K3', 'Kimi K3')
    assert model.prices == ModelPrice(
        input_mtok=Decimal('3'), cache_read_mtok=Decimal('0.3'), output_mtok=Decimal('15')
    )
    assert source_modal.parse_model_data(model_page(RATES | {'reasoningMtok': '15.00'})) is not None


def test_modal_skips_models_without_a_shared_endpoint() -> None:
    assert source_modal.parse_model_data(model_page(None, shared=False)) is None


@pytest.mark.parametrize(
    ('data', 'error'),
    [
        (svelte_data([{'title': 1}, 'Not found']), 'Modal model page has no model'),
        (model_page(None), 'Modal Shared Endpoint model has no token rates'),
        (model_page(RATES | {'promptMtok': 'TBD'}), "Unexpected Modal promptMtok rate 'TBD'"),
        (model_page(RATES | {'reasoningMtok': '20.00'}), 'Modal prices reasoning tokens separately'),
    ],
)
def test_modal_rejects_an_unexpected_model_page(data: dict[str, Any], error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_modal.parse_model_data(data)


@pytest.mark.vcr()
def test_modal_main_fetches_recorded_library(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'modal.yml'
    copyfile(package_dir / 'providers/modal.yml', provider_path)

    source_modal.main(provider_path)

    assert capsys.readouterr().out == 'Modal prices updated: 0 added, 8 updated\n'
