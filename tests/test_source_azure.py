from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile
from typing import Any

import pytest

from prices import source_azure
from prices.prices_types import ModelPrice
from prices.utils import package_dir


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


@pytest.mark.parametrize(
    ('items', 'error'),
    [
        (_items()[1:], "no meter 'embedding-ada-glbl Tokens' for ada"),
        ([*_items(), _items()[0]], "meter 'embedding-ada-glbl Tokens' more than once"),
        ([{**_items()[0], 'unitOfMeasure': '1/Hour'}, *_items()[1:]], "Unexpected Azure unit '1/Hour'"),
    ],
)
def test_azure_rejects_unexpected_retail_prices(items: list[dict[str, Any]], error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_azure.parse_retail_prices(items)


@pytest.mark.vcr()
def test_azure_main_fetches_recorded_retail_prices(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'azure.yml'
    copyfile(package_dir / 'providers/azure.yml', provider_path)

    source_azure.main(provider_path)

    assert capsys.readouterr().out == 'Azure prices updated: 0 added, 15 updated\n'
