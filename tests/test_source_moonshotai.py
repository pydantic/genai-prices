from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_moonshotai
from prices.prices_types import ClauseStartsWith, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

K3_COLUMNS = """\
{ title: "Model", width: "12%" },
{ title: "Unit", width: "10%" },
{ title: "Cache Write Price (TTL 5min)", width: "13%" },
{ title: "Cache Write Price (TTL 1h)", width: "13%" },
{ title: "Cached Input Price", width: "13%" },
{ title: "Input Price", width: "13%" },
{ title: "Output Price", width: "10%" },
{ title: "Context Window", width: "16%" },
"""
K3_ROW = (
    '["kimi-k3", "1M tokens", <>{"$"}3.00</>, <>{"$"}6.00</>, <>{"$"}0.30</>, <>{"$"}3.00</>, <>{"$"}15.00</>,'
    ' "1,048,576 tokens"],'
)
K2_COLUMNS = """\
{ title: "Model", width: "24%" },
{ title: "Unit", width: "12%" },
{ title: "Input Price (Cache Hit)", width: "16%" },
{ title: "Input Price (Cache Miss)", width: "16%" },
{ title: "Output Price", width: "14%" },
{ title: "Context Window", width: "18%" },
"""
K2_ROW = '["kimi-k2.6", "1M tokens", <>{"$"}0.16</>, <>{"$"}0.95</>, <>{"$"}4.00</>, "262,144 tokens"],'


def doc_table(columns: str, *rows: str) -> str:
    body = '\n'.join(rows)
    return f'<DocTable\n  columns={{[\n{columns}]}}\n  rows={{[\n{body}\n]}}\n/>\n'


def test_moonshot_maps_columns_by_title() -> None:
    models = source_moonshotai.parse_pricing_markdown(doc_table(K3_COLUMNS, K3_ROW) + doc_table(K2_COLUMNS, K2_ROW))

    assert [(model.id, model.context_window) for model in models] == [('kimi-k3', 1048576), ('kimi-k2.6', 262144)]
    assert models[0].prices == ModelPrice.model_validate(
        {
            'input_mtok': '3',
            'cache_read_mtok': '0.3',
            'cache_write_mtok': '3',
            'cache_write_1h_mtok': '6',
            'output_mtok': '15',
        }
    )
    assert models[1].prices == ModelPrice(
        input_mtok=Decimal('0.95'), cache_read_mtok=Decimal('0.16'), output_mtok=Decimal('4')
    )
    assert models[1].prices_checked == date.today()


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        ('## Model Pricing\n', 'has no DocTable price tables'),
        (
            doc_table(K2_COLUMNS.replace('Output Price', 'Batch Price'), K2_ROW),
            'Unexpected Moonshot AI pricing columns',
        ),
        (doc_table(K2_COLUMNS, K2_ROW.replace(', "262,144 tokens"', '')), 'Unexpected Moonshot AI pricing row'),
        (doc_table(K2_COLUMNS, K2_ROW.replace('<>{"$"}4.00</>', '4.00')), 'Unexpected Moonshot AI pricing row'),
        (doc_table(K2_COLUMNS, K2_ROW.replace('1M tokens', '1K tokens')), 'unit or context window'),
        (doc_table(K2_COLUMNS, K2_ROW.replace('<>{"$"}4.00</>', '"-"')), 'Unexpected Moonshot AI Output Price'),
    ],
)
def test_moonshot_rejects_unexpected_tables(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_moonshotai.parse_pricing_markdown(markdown)


@pytest.mark.vcr()
def test_moonshot_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'moonshotai.yml'
    copyfile(package_dir / 'providers/moonshotai.yml', provider_path)

    source_moonshotai.main(provider_path)

    assert capsys.readouterr().out == 'Moonshot AI prices updated: 0 added, 4 updated\n'
    kimi_k26 = ProviderYaml(provider_path).provider.find_model('kimi-k2.6')
    assert kimi_k26 is not None
    assert kimi_k26.match == ClauseStartsWith(starts_with='kimi-k2.6')
