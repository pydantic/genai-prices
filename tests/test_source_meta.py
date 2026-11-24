from __future__ import annotations

from datetime import date

import pytest

from prices import source_meta
from prices.prices_types import ModelPrice

from .fixtures import ProviderSnapshot

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


@pytest.mark.parametrize('table', [TABLE, SWAPPED_TABLE], ids=['standard-first', 'contributor-first'])
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


def test_meta_rejects_a_page_without_model_pricing() -> None:
    with pytest.raises(RuntimeError, match='no longer has a model pricing section with a web search rate'):
        source_meta.parse_pricing_markdown('## Model pricing\n\n## Rate limits\n')


EMBER = f'### Muse Ember\n\nModel: `muse-ember-1.0`, in Standard mode only.\n\n{LONG_CONTEXT_TABLE}\n'
SPARK = f'### Muse Spark\n\nModel: `muse-spark-1.3`.\n\n{TABLE}\n'
SKIPPED = 'Meta: skipped a row it cannot read; update it by hand. '
SKIPPED_SPARK = 'Meta: skipped a row it cannot read for muse-spark-1.3; update it by hand. '


@pytest.mark.parametrize(
    ('family', 'note', 'model_ids'),
    [
        (f'### Muse Spark\n\n{TABLE}', f'{SKIPPED}Unexpected Meta pricing layout for Muse Spark', ['muse-ember-1.0']),
        (
            '### Muse Spark\n\nModel: `muse-spark-1.3`.\n',
            f'{SKIPPED_SPARK}Unexpected Meta pricing layout for Muse Spark',
            ['muse-ember-1.0'],
        ),
        (
            SPARK.replace('Cached input', 'Cache write'),
            f'{SKIPPED_SPARK}Unexpected Meta pricing layout for Muse Spark',
            ['muse-ember-1.0'],
        ),
        (
            f'### Muse Spark\n\nModels: Muse Spark 1.3.\n\n{TABLE}',
            f'{SKIPPED}No Meta model ids listed for Muse Spark',
            ['muse-ember-1.0'],
        ),
        (
            f'### Muse Spark\n\nModels: `muse-spark-1.3-contributor` and `muse-spark-1.3`.\n\n{TABLE.replace("$0.002", "Free")}',
            'Meta: skipped a row it cannot read for muse-spark-1.3-contributor; update it by hand. '
            'Unexpected Meta price for muse-spark-1.3-contributor: Free',
            ['muse-ember-1.0', 'muse-spark-1.3'],
        ),
        (
            f'### Muse Ember Contributor\n\nModel: `muse-ember-1.0-contributor`.\n\n{LONG_CONTEXT_TABLE}',
            'Meta: skipped a row it cannot read for muse-ember-1.0-contributor; update it by hand. '
            'Meta lists no Contributor mode long-context prices for muse-ember-1.0-contributor',
            ['muse-ember-1.0'],
        ),
        (
            # A readable later occurrence of a model does not price it when an earlier one is unreadable.
            SPARK.replace('$1.25', 'Free') + SPARK,
            f'{SKIPPED_SPARK}Unexpected Meta price for muse-spark-1.3: Free',
            ['muse-ember-1.0'],
        ),
        (
            SPARK.replace('Cached input', 'Cache write') + SPARK,
            f'{SKIPPED_SPARK}Unexpected Meta pricing layout for Muse Spark',
            ['muse-ember-1.0'],
        ),
    ],
)
def test_meta_reports_an_unreadable_family_or_model_and_reads_the_others(
    family: str, note: str, model_ids: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    models = source_meta.parse_pricing_markdown(page(EMBER + family))

    assert [model.id for model in models] == model_ids
    assert capsys.readouterr().out == f'{note}\n'


def test_meta_keeps_a_model_listed_more_than_once_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    models = source_meta.parse_pricing_markdown(
        page(f'{EMBER}### Muse Spark\n\nModels: `muse-spark-1.3` and `muse-spark-1.3`.\n\n{TABLE}')
    )

    assert [model.id for model in models] == ['muse-ember-1.0']
    assert capsys.readouterr().out == (
        'Meta: kept muse-spark-1.3 unchanged, the pricing page lists it more than once; update it by hand\n'
    )


@pytest.mark.vcr()
def test_meta_main_fetches_recorded_pricing_page(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('meta.yml')

    source_meta.main(provider_path)

    assert capsys.readouterr().out == 'Meta prices updated: 0 added, 6 updated\n'
