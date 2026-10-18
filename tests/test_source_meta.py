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


def test_meta_parses_standard_and_contributor_models_with_web_search() -> None:
    family = f"""\
### Muse Spark

Models: `muse-spark-1.3` in Standard mode; `muse-spark-1.3-contributor` in Contributor mode.

{TABLE}"""
    models = source_meta.parse_pricing_markdown(page(family))

    assert [model.id for model in models] == ['muse-spark-1.3', 'muse-spark-1.3-contributor']
    assert models[0].prices == ModelPrice.model_validate(
        {'input_mtok': '1.25', 'cache_read_mtok': '0.15', 'output_mtok': '4.25', 'web_searches_kcount': '2.50'}
    )
    assert models[1].prices == ModelPrice.model_validate(
        {'input_mtok': '0.10', 'cache_read_mtok': '0.002', 'output_mtok': '0.20', 'web_searches_kcount': '2.50'}
    )
    assert models[1].prices_checked == date.today()


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
