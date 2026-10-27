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


def tooltip(label: str) -> str:
    return f'_jsx(Tooltip,{{tip:`About {label}.`,children:`{label}`}})'


def link(model_id: str) -> str:
    return f'_jsx(_components.a,{{href:`/guide/{model_id}-quickstart`,children:`{model_id}`}})'


K3_COLUMNS = (
    '{title:`Model`,width:`25%`},{title:`Input`,width:`15%`},{title:`Output`,width:`15%`},'
    f'{{title:{tooltip("Cached Input")},width:`15%`}},{{title:{tooltip("5m writes")},width:`15%`}},'
    f'{{title:{tooltip("1h writes")},width:`15%`}}'
)
K3_ROW = f'[{link("kimi-k3")},`$3.00 / MTok`,`$15.00 / MTok`,`$0.30 / MTok`,`$3.00 / MTok`,`$6.00 / MTok`]'
K2_COLUMNS = (
    '{title:`Model`,width:`34%`},{title:`Input`,width:`22%`},{title:`Output`,width:`22%`},'
    f'{{title:{tooltip("Cached Input")},width:`22%`}}'
)
K2_ROW = f'[{link("kimi-k2.6")},`$0.95 / MTok`,`$4.00 / MTok`,`$0.16 / MTok`]'


def section(context: str, columns: str, *rows: str) -> str:
    return (
        f'_jsx(_components.p,{{children:`All models support a {context}-token context window.`}}),`\\n`,'
        f'_jsx(DocTable,{{className:`doc-table-bordered`,columns:[{columns}],rows:[{",".join(rows)}]}})}}),`\\n`,'
    )


def test_moonshot_maps_columns_by_title_and_reads_each_sections_context_window() -> None:
    models = source_moonshotai.parse_pricing_page(
        section('1,048,576', K3_COLUMNS, K3_ROW) + section('262,144', K2_COLUMNS, K2_ROW)
    )

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
    ('page', 'error'),
    [
        ('<table><tbody /></table>', 'has no DocTable price tables'),
        (
            section('262,144', K2_COLUMNS.replace('`Output`', '`Batch`'), K2_ROW),
            'Unexpected Moonshot AI pricing columns',
        ),
        (
            section('262,144', K2_COLUMNS.replace('{title:`Output`,width:`22%`},', ''), K2_ROW),
            'Unexpected Moonshot AI pricing columns',
        ),
        (
            section('262,144', K2_COLUMNS.replace('`Output`', '`Input`'), K2_ROW),
            'Unexpected Moonshot AI pricing columns',
        ),
        (section('262,144', K2_COLUMNS, K2_ROW).replace('All models support', 'All models have'), 'no context window'),
        (section('262,144', K2_COLUMNS, K2_ROW.replace(',`$0.16 / MTok`', '')), 'Unexpected Moonshot AI pricing row'),
        (
            section('262,144', K2_COLUMNS, K2_ROW.replace('`kimi-k2.6`', '`Kimi K2.6`')),
            'Unexpected Moonshot AI pricing row',
        ),
        (
            section('262,144', K2_COLUMNS, K2_ROW.replace('`$4.00 / MTok`', '`-`')),
            'Unexpected Moonshot AI Output for kimi-k2.6: -',
        ),
    ],
)
def test_moonshot_rejects_unexpected_tables(page: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_moonshotai.parse_pricing_page(page)


@pytest.mark.vcr()
def test_moonshot_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'moonshotai.yml'
    copyfile(package_dir / 'providers/moonshotai.yml', provider_path)

    source_moonshotai.main(provider_path)

    assert capsys.readouterr().out == 'Moonshot AI prices updated: 2 added, 4 updated\n'
    kimi_k26 = ProviderYaml(provider_path).provider.find_model('kimi-k2.6')
    assert kimi_k26 is not None
    assert kimi_k26.match == ClauseStartsWith(starts_with='kimi-k2.6')
