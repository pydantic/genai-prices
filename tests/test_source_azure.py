from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from typing import Any

import httpx2
import pytest

from prices import source_azure
from prices.prices_types import ModelPrice

from .fixtures import ProviderSnapshot


def _items() -> list[dict[str, Any]]:
    return [
        {'meterName': meter, 'unitOfMeasure': '1K', 'retailPrice': 0.0011}
        for meters in source_azure.METERS.values()
        for meter in meters.values()
    ]


def test_azure_parses_mapped_meters_into_per_million_rates() -> None:
    models = source_azure.parse_retail_prices(
        [
            *_items()[:-1],
            {'meterName': 'text-embedding-3-small-glbl Tokens', 'unitOfMeasure': '1M', 'retailPrice': 60.0},
        ]
    )

    assert [model.id for model in models] == list(source_azure.METERS)
    assert models[1].prices == ModelPrice(
        input_mtok=Decimal('1.1'), cache_read_mtok=Decimal('1.1'), output_mtok=Decimal('1.1')
    )
    assert repr(models[-1].prices) == repr(ModelPrice(input_mtok=Decimal('60')))
    assert models[0].prices_checked == date.today()


SKIPPED = 'Azure: skipped a row it cannot read; update it by hand. '
NO_ADA_METER = f"{SKIPPED}Azure retail prices have no meter 'embedding-ada-glbl Tokens' for ada\n"


@pytest.mark.parametrize(
    ('items', 'notes'),
    [
        (_items()[1:], NO_ADA_METER),
        (
            [*_items(), _items()[0]],
            "Azure: kept ada unchanged, the retail prices list meter 'embedding-ada-glbl Tokens' more than once; "
            'update it by hand\n',
        ),
        (
            [{**_items()[0], 'unitOfMeasure': '1/Hour'}, *_items()[1:]],
            f"{SKIPPED}Unexpected Azure unit '1/Hour' for meter 'embedding-ada-glbl Tokens'\n{NO_ADA_METER}",
        ),
    ],
)
def test_azure_reports_an_unreadable_meter_and_reads_the_other_models(
    items: list[dict[str, Any]], notes: str, capsys: pytest.CaptureFixture[str]
) -> None:
    models = source_azure.parse_retail_prices(items)

    assert [model.id for model in models] == list(source_azure.METERS)[1:]
    assert capsys.readouterr().out == notes


@pytest.mark.vcr()
def test_azure_main_fetches_recorded_retail_prices(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('azure.yml')

    source_azure.main(provider_path)

    assert capsys.readouterr().out == 'Azure prices updated: 0 added, 15 updated\n'


@pytest.mark.parametrize(('throttled', 'error'), [(2, None), (3, '429 Too Many Requests')])
def test_azure_main_retries_throttled_requests(
    monkeypatch: pytest.MonkeyPatch, provider_snapshot: ProviderSnapshot, throttled: int, error: str | None
) -> None:
    provider_path = provider_snapshot('azure.yml')
    responses = [
        httpx2.Response(429, headers={'Retry-After': '60'}, request=httpx2.Request('GET', source_azure.PRICES_URL))
    ] * throttled
    sleeps: list[float] = []

    def get(url: str, params: dict[str, str], **_: object) -> httpx2.Response:
        if responses:
            return responses.pop()
        items = [item for item in _items() if f"meterName eq '{item['meterName']}'" in params['$filter']]
        return httpx2.Response(200, json={'Items': items}, request=httpx2.Request('GET', url))

    monkeypatch.setattr(httpx2, 'get', get)
    monkeypatch.setattr(time, 'sleep', sleeps.append)

    if error is None:
        source_azure.main(provider_path)
    else:
        with pytest.raises(httpx2.HTTPStatusError, match=error):
            source_azure.main(provider_path)
    assert sleeps == [60, 60]
