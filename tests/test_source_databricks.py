from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from shutil import copyfile
from typing import Any

import pytest

from prices import source_databricks
from prices.prices_types import ModelPrice
from prices.utils import package_dir

TABLE = (
    '<h2>Foundation Model Serving DBU rates</h2><h3>Pay Per Token</h3><table><thead><tr><th>Model</th>'
    '<th>Pay Per Token (DBU Per 1M Tokens)</th></tr></thead><tbody>'
    '<tr><td>Kimi K3 ⌖</td><td style="text-align:right;">42.857</td><td>214.286</td><td>4.286</td></tr>'
    '<tr><td>GLM-5.2, 5.3</td><td>20.000</td><td>62.857</td><td>3.714</td></tr>'
    '<tr><td>BGE Large</td><td>1.429</td><td>-</td><td>-</td></tr>'
    '<tr><td>Brand New Model</td><td>1.000</td><td>2.000</td><td>-</td></tr>'
    '</tbody></table><h3>Priority Pay Per Token</h3><table><tbody>'
    '<tr><td>Kimi K3 ⌖</td><td>75.000</td><td>375.000</td><td>7.500</td></tr></tbody></table>'
)


def page_data(table: str = TABLE, clouds: list[str] | None = None) -> dict[str, Any]:
    def block(table: str, clouds: list[str]) -> dict[str, Any]:
        return {
            'fieldItem': {'entity': {'fieldPricingClouds': clouds}},
            'fieldDescription': {'processed': table},
        }

    return {
        'result': {
            'data': {
                'fieldItems': [
                    {'fieldDescription': None, 'fieldItem': None},
                    block(table.replace('62.857', '99.000'), ['azure']),
                    block(table, clouds or ['aws', 'google']),
                ]
            }
        }
    }


def test_databricks_converts_dbu_rates_to_usd(capsys: pytest.CaptureFixture[str]) -> None:
    models = source_databricks.parse_page_data(page_data())

    assert {model.id: model.prices for model in models} == {
        'databricks-kimi-k3': ModelPrice(
            input_mtok=Decimal('3.000'), output_mtok=Decimal('15.000'), cache_read_mtok=Decimal('0.300')
        ),
        'databricks-glm-5-2': ModelPrice(
            input_mtok=Decimal('1.400'), output_mtok=Decimal('4.400'), cache_read_mtok=Decimal('0.260')
        ),
        'databricks-glm-5-3': ModelPrice(
            input_mtok=Decimal('1.400'), output_mtok=Decimal('4.400'), cache_read_mtok=Decimal('0.260')
        ),
        'databricks-bge-large-en': ModelPrice(input_mtok=Decimal('0.100')),
    }
    assert capsys.readouterr().out == "Databricks: skipped 'Brand New Model', it has no known serving endpoint\n"


@pytest.mark.parametrize(
    ('data', 'error'),
    [
        (page_data(clouds=['azure']), 'Expected one Databricks AWS pay-per-token table, found 0'),
        (page_data(TABLE.replace('<tbody>', '<tbody >')), 'Databricks pay-per-token table has no body'),
        (page_data(TABLE.replace('<td>-</td><td>-</td>', '<td>-</td>')), 'Unexpected Databricks pricing row'),
        (page_data(TABLE.replace('20.000', '20 DBU')), "Unexpected Databricks DBU rate '20 DBU'"),
    ],
)
def test_databricks_rejects_an_unexpected_pricing_table(data: dict[str, Any], error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_databricks.parse_page_data(data)


@pytest.mark.vcr()
def test_databricks_main_fetches_recorded_page_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'databricks.yml'
    copyfile(package_dir / 'providers/databricks.yml', provider_path)

    source_databricks.main(provider_path)

    assert capsys.readouterr().out == 'Databricks prices updated: 0 added, 20 updated\n'
