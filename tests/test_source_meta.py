from __future__ import annotations

from datetime import date
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_meta
from prices.prices_types import ModelPrice
from prices.utils import package_dir

TABLE = """\
| Usage        | Standard mode (per 1M tokens) | Contributor mode (per 1M tokens) |
| :----------- | :---------------------------- | :------------------------------- |
| Cached input | $0.15                         | $0.002                           |
| Input        | $1.25                         | $0.10                            |
| Output       | $4.25                         | $0.20                            |
"""
# Meta has published the mode columns in both orders.
SWAPPED_TABLE = """\
| Usage        | Contributor mode (per 1M tokens) | Standard mode (per 1M tokens) |
| :----------- | :------------------------------- | :---------------------------- |
| Cached input | $0.002                           | $0.15                         |
| Input        | $0.10                            | $1.25                         |
| Output       | $0.20                            | $4.25                         |
"""
LONG_CONTEXT_TABLE = """\
| Usage        | Up to 200K input tokens (per 1M tokens) | Over 200K input tokens (per 1M tokens) |
| :----------- | :-------------------------------------- | :------------------------------------- |
| Cached input | $0.004                                  | $0.012                                 |
| Input        | $0.10                                   | $0.30                                  |
| Output       | $0.50                                   | $1.50                                  |
"""


def page(family: str) -> str:
    return f"""\
## Model pricing

{family}

### Token pricing notes

- **Web search grounding**: **$2.50 per 1,000 search queries**, in addition to the request's token cost.

### Muse Image

| Usage           | Price           |
| :-------------- | :-------------- |
| Generated image | $0.01 per image |

## Rate limits
"""


@pytest.mark.parametrize('table', [TABLE, SWAPPED_TABLE])
def test_meta_parses_standard_and_contributor_models_with_web_search(table: str) -> None:
    family = f"""\
### Muse Spark

Models: `muse-spark-1.3` in Standard mode; `muse-spark-1.3-contributor` in Contributor mode.

{table}"""
    models = source_meta.parse_pricing_markdown(page(family))

    assert [model.id for model in models] == ['muse-spark-1.3', 'muse-spark-1.3-contributor']
    assert models[0].prices == ModelPrice.model_validate(
        {'input_mtok': '1.25', 'cache_read_mtok': '0.15', 'output_mtok': '4.25', 'web_searches_kcount': '2.50'}
    )
    assert models[1].prices == ModelPrice.model_validate(
        {'input_mtok': '0.10', 'cache_read_mtok': '0.002', 'output_mtok': '0.20', 'web_searches_kcount': '2.50'}
    )
    assert models[1].prices_checked == date.today()


def test_meta_parses_long_context_tiers() -> None:
    models = source_meta.parse_pricing_markdown(
        page(f'### Muse Ember\n\nModel: `muse-ember-1.0`, in Standard mode only.\n\n{LONG_CONTEXT_TABLE}')
    )

    assert [model.id for model in models] == ['muse-ember-1.0']
    assert models[0].prices == ModelPrice.model_validate(
        {
            'input_mtok': {'base': '0.10', 'tiers': [{'start': 200_000, 'price': '0.30'}]},
            'cache_read_mtok': {'base': '0.004', 'tiers': [{'start': 200_000, 'price': '0.012'}]},
            'output_mtok': {'base': '0.50', 'tiers': [{'start': 200_000, 'price': '1.50'}]},
            'web_searches_kcount': '2.50',
        }
    )


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        ('## Model pricing\n\n## Rate limits\n', 'no longer has a model pricing section with a web search rate'),
        (page(f'### Muse Spark\n\n{TABLE}'), 'Unexpected Meta pricing layout for Muse Spark'),
        (page('### Muse Spark\n\nModel: `muse-spark-1.3`.\n'), 'Unexpected Meta pricing layout for Muse Spark'),
        (
            page(f'### Muse Spark\n\nModel: `muse-spark-1.3`.\n\n{TABLE.replace("Cached input", "Cache write")}'),
            'Unexpected Meta pricing layout for Muse Spark',
        ),
        (page(f'### Muse Spark\n\nModels: Muse Spark 1.3.\n\n{TABLE}'), 'No Meta model ids listed for Muse Spark'),
        (
            page(f'### Muse Spark\n\nModels: `muse-spark-1.3` and `muse-spark-1.3`.\n\n{TABLE}'),
            'Duplicate Meta model in pricing data: muse-spark-1.3',
        ),
        (
            page(f'### Muse Spark\n\nModel: `muse-spark-1.3-contributor`.\n\n{TABLE.replace("$0.002", "Free")}'),
            'Unexpected Meta price for muse-spark-1.3-contributor: Free',
        ),
        (
            page(f'### Muse Ember\n\nModel: `muse-ember-1.0-contributor`.\n\n{LONG_CONTEXT_TABLE}'),
            'Meta lists no Contributor mode long-context prices for muse-ember-1.0-contributor',
        ),
    ],
)
def test_meta_rejects_unexpected_pricing_layout(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_meta.parse_pricing_markdown(markdown)


@pytest.mark.vcr()
def test_meta_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'meta.yml'
    copyfile(package_dir / 'providers/meta.yml', provider_path)

    source_meta.main(provider_path)

    assert capsys.readouterr().out == 'Meta prices updated: 0 added, 6 updated\n'
