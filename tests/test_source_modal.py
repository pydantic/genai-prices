from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from prices import source_modal
from prices.prices_types import ModelPrice

from .fixtures import ProviderSnapshot


def svelte_data(values: list[Any]) -> dict[str, Any]:
    return {'type': 'data', 'nodes': [{'type': 'data', 'data': [{}]}, {'type': 'data', 'data': values}]}


def model_page(
    rates: dict[str, str] | None, *, shared: bool = True, model_id: str = 'moonshotai/Kimi-K3'
) -> dict[str, Any]:
    values: list[Any] = [
        {'model': 1},
        {'baseModelRepoId': 2, 'displayName': 3, 'hasSharedEndpoint': 4, 'tokenRates': 5 if rates else -1},
        model_id,
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


def test_modal_rejects_a_library_without_models() -> None:
    with pytest.raises(RuntimeError, match='Modal library page has no models'):
        source_modal.parse_library_data(svelte_data([{'title': 1}, 'Model Library']))


def test_modal_reports_an_unreadable_library_link_and_reads_the_others(capsys: pytest.CaptureFixture[str]) -> None:
    data = svelte_data(
        [
            {'models': 1},
            [2, 3, 4],
            {'href': 5},
            {'name': 6},
            {'href': 7},
            'https://example.com',
            'Kimi K3',
            '/library/k3',
        ]
    )

    assert source_modal.parse_library_data(data) == ['/library/k3']
    assert capsys.readouterr().out == (
        "Modal: skipped a row it cannot read; update it by hand. Unexpected Modal library model link: 'https://example.com'\n"
        'Modal: skipped a row it cannot read; update it by hand. Unexpected Modal library model link: None\n'
    )


def test_modal_shared_endpoint_token_rates() -> None:
    model = source_modal.parse_model_data('/library/kimi-k3', model_page(RATES))

    assert model is not None
    assert (model.id, model.name) == ('moonshotai/Kimi-K3', 'Kimi K3')
    assert model.prices == ModelPrice(
        input_mtok=Decimal('3'), cache_read_mtok=Decimal('0.3'), output_mtok=Decimal('15')
    )
    assert source_modal.parse_model_data('/library/kimi-k3', model_page(RATES | {'reasoningMtok': '15.00'})) is not None


def test_modal_skips_models_without_a_shared_endpoint() -> None:
    assert source_modal.parse_model_data('/library/kimi-k3', model_page(None, shared=False)) is None


@pytest.mark.parametrize(
    ('data', 'error'),
    [
        (svelte_data([{'title': 1}, 'Not found']), 'Modal model page /library/b has no model'),
        (model_page(None), 'Modal Shared Endpoint model has no token rates'),
        (model_page(RATES | {'promptMtok': 'TBD'}), "Unexpected Modal promptMtok rate 'TBD' for moonshotai/Kimi-K3"),
        (
            model_page(RATES | {'reasoningMtok': '20.00'}),
            'Modal prices reasoning tokens separately for moonshotai/Kimi-K3',
        ),
    ],
)
def test_modal_reports_an_unreadable_model_page_and_reads_the_others(
    data: dict[str, Any],
    error: str,
    monkeypatch: pytest.MonkeyPatch,
    provider_snapshot: ProviderSnapshot,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider_path = provider_snapshot('modal.yml')
    pages = {
        '/library/__data.json': svelte_data(
            [{'models': 1}, [2, 3, 4], {'href': 5}, {'href': 6}, {'href': 7}, '/library/a', '/library/b', '/library/c']
        ),
        '/library/a/__data.json': model_page(RATES, model_id='zai-org/GLM-5.3'),
        '/library/b/__data.json': data,
        '/library/c/__data.json': model_page(RATES, model_id='zai-org/GLM-5.3-Flash'),
    }

    def get_json(_client: object, path: str) -> dict[str, Any]:
        return pages[path]

    monkeypatch.setattr(source_modal, '_get_json', get_json)

    source_modal.main(provider_path)

    note, summary = capsys.readouterr().out.splitlines()
    assert note.startswith(f'Modal: skipped a row it cannot read; update it by hand. {error}')
    assert summary == 'Modal prices updated: 0 added, 2 updated'


@pytest.mark.vcr()
def test_modal_main_fetches_recorded_library(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('modal.yml')

    source_modal.main(provider_path)

    assert capsys.readouterr().out == 'Modal prices updated: 0 added, 8 updated\n'
