from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from prices import source_zai
from prices.prices_types import ClauseEquals, ClauseOr, ModelPrice
from prices.utils import markdown_tables

from .fixtures import ProviderSnapshot

HEADER = """\
| Model | Input | Cached Input | Cached Input Storage | Output |
| :- | :- | :- | :- | :- |
"""
PRICING_MARKDOWN = f"""\
### Latest Models

{HEADER}\
| GLM-5.3-Flash | \\$0.15 | \\$0.03 | Limited-time Free | \\$0.50 |
| GLM-4-32B-0414-128K | \\$0.1 | - | - | \\$0.1 |

Model | Input | Cached Input | Cached Input Storage | Output
:- | :- | :- | :- | :-
GLM-4.5 | \\$0.6 | \\$0.11 | Free \\| for now | \\$2.2

Prices | are per 1M tokens
| :- |

### Built-in Tools

| Tool | Cost |
| :- | :- |
| Web Search | \\$0.01 / use |

> **Other Pricing**
>
> ### Vision Models
>
> | Model | Input | Cached Input | Cached Input Storage | Output |
> | :- | :- | :- | :- | :- |
   > | GLM-OCR | \\$0.03 | \\\\ | \\\\ | \\$0.03 |
> | GLM-4.6V-Flash | Free | Free | Free | Free |
>
> | Model | Price |
> | :- | :- |
> | CogView-4 | \\$0.01 |
"""


def test_zai_parses_token_tables_and_skips_free_and_non_token_models() -> None:
    models = source_zai.parse_pricing_markdown(PRICING_MARKDOWN)

    assert [model.id for model in models] == ['GLM-5.3-Flash', 'GLM-4-32B-0414-128K', 'GLM-4.5', 'GLM-OCR']
    assert models[0].name == 'GLM-5.3-Flash'
    assert models[0].match == ClauseOr.model_validate(
        {'or': [ClauseEquals(equals='GLM-5.3-Flash'), ClauseEquals(equals='glm-5.3-flash')]}
    )
    assert models[0].prices == ModelPrice(
        input_mtok=Decimal('0.15'), cache_read_mtok=Decimal('0.03'), output_mtok=Decimal('0.50')
    )
    assert models[1].prices == ModelPrice(input_mtok=Decimal('0.1'), output_mtok=Decimal('0.1'))
    assert models[2].prices == ModelPrice(
        input_mtok=Decimal('0.6'), cache_read_mtok=Decimal('0.11'), output_mtok=Decimal('2.2')
    )
    assert markdown_tables(PRICING_MARKDOWN)[1][1] == [['GLM-4.5', '\\$0.6', '\\$0.11', 'Free | for now', '\\$2.2']]
    assert models[3].prices == ModelPrice(input_mtok=Decimal('0.03'), output_mtok=Decimal('0.03'))
    assert models[3].prices_checked == date.today()


def test_zai_rejects_unexpected_token_pricing_columns() -> None:
    with pytest.raises(RuntimeError, match='Unexpected Z.ai token pricing columns'):
        source_zai.parse_pricing_markdown('| Model | Input | Output |\n| :- | :- | :- |\n')


def test_zai_reports_an_unreadable_price_and_reads_the_other_rows(capsys: pytest.CaptureFixture[str]) -> None:
    models = source_zai.parse_pricing_markdown(
        HEADER + '| GLM-5 | $1 | \\$0.2 | Free | \\$3.2 |\n| GLM-5.1 | \\$1 | \\$0.2 | Free | \\$3.2 |\n'
    )

    assert [model.id for model in models] == ['GLM-5.1']
    assert (
        capsys.readouterr().out
        == 'Z.ai: skipped a row it cannot read; update it by hand. Unexpected Z.ai price cell for GLM-5: $1\n'
    )


def test_zai_keeps_a_duplicated_model_unchanged_and_reports_it(capsys: pytest.CaptureFixture[str]) -> None:
    models = source_zai.parse_pricing_markdown(
        HEADER + '| GLM-5 | \\$1 | \\$0.2 | Free | \\$3.2 |\n' * 2 + '| GLM-5.1 | \\$1 | \\$0.2 | Free | \\$3.2 |\n'
    )

    assert [model.id for model in models] == ['GLM-5.1']
    assert capsys.readouterr().out == (
        'Z.ai: kept GLM-5 unchanged, the pricing page lists it more than once; update it by hand\n'
    )


@pytest.mark.vcr()
def test_zai_main_fetches_recorded_pricing_page(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('zai.yml')

    source_zai.main(provider_path)

    assert capsys.readouterr().out == 'Z.ai prices updated: 0 added, 18 updated\n'
