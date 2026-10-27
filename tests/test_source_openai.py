from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_openai
from prices.prices_types import ClauseEquals, ModelPrice, Tier, TieredPrices
from prices.utils import package_dir

CONTEXT_TIER_HEADER = (
    '| Model | Short context input | Short context output | Short context cached input | Short context 30m write '
    '| Short context 12h write | Long context input | Long context output | Long context cached input '
    '| Long context 30m write | Long context 12h write |'
)
PRICING_MARKDOWN = f"""\
Standard

### Standard pricing data

{CONTEXT_TIER_HEADER}
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-7 (<272K context length) | $2.00 | $10.00 | $0.20 | $2.50 | $5.00 | $4.00 | $15.00 | $0.40 | $5.00 | $10.00 |
| gpt-7-pro | $30.00 | $180.00 | - | - | - | - | - | - | - | - |

Batch

### Batch pricing data

{CONTEXT_TIER_HEADER}
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gpt-7-pro | $15.00 | $90.00 | - | - | - | - | - | - | - | - |

Prices per 1M tokens.

### Grouped Pricing Table data

| Model | Input | Output | Cached input |
| --- | --- | --- | --- |
| gpt-7-pro | $30.00 | $180.00 | - |
| gpt-bio | $5.00 | $25.00 | $0.50 |

### Grouped Pricing Table data

| Model | Modality | Input | Cached input | Output |
| --- | --- | --- | --- | --- |
| gpt-image-9 | Image | $8.00 | $2.00 | $30.00 |

Standard

### Grouped Pricing Table data

| Category | Model | Input | Cached input | Output |
| --- | --- | --- | --- | --- |
| Embedding | text-embedding-9 | $0.02 | - | - |
| Moderation | omni-moderation-latest | Free | - | - |
"""


def tiered(base: str, price: str) -> TieredPrices:
    return TieredPrices(base=Decimal(base), tiers=[Tier(start=272_000, price=Decimal(price))])


def test_openai_parses_standard_text_rates_and_skips_other_tabs_and_units() -> None:
    models = source_openai.parse_pricing_markdown(PRICING_MARKDOWN)

    assert [(m.id, m.match, m.prices_checked) for m in models] == [
        (model_id, ClauseEquals(equals=model_id), date.today())
        for model_id in ('gpt-7', 'gpt-7-pro', 'gpt-bio', 'text-embedding-9')
    ]
    assert [m.prices for m in models] == [
        ModelPrice(
            input_mtok=tiered('2', '4'),
            cache_read_mtok=tiered('0.2', '0.4'),
            cache_write_mtok=tiered('2.5', '5'),
            output_mtok=tiered('10', '15'),
        ),
        ModelPrice(input_mtok=Decimal(30), output_mtok=Decimal(180)),
        ModelPrice(input_mtok=Decimal(5), cache_read_mtok=Decimal('0.5'), output_mtok=Decimal(25)),
        ModelPrice(input_mtok=Decimal('0.02')),
    ]


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        ('# Pricing\n', 'OpenAI pricing page has no standard text pricing table'),
        (PRICING_MARKDOWN.replace('| gpt-bio |', '| GPT Bio |'), 'Unexpected OpenAI pricing row'),
        (PRICING_MARKDOWN.replace('$25.00', 'TBD'), "Unexpected OpenAI price 'TBD'"),
        (PRICING_MARKDOWN.replace('| $0.20 | $2.50 |', '| $0.20 | - |'), 'without its pair'),
        (PRICING_MARKDOWN.replace('| $0.40 | $5.00 |', '| $0.40 | - |'), 'without its pair'),
        (
            PRICING_MARKDOWN.replace(
                '| gpt-7-pro | $30.00 | $180.00 | - |\n', '| gpt-7-pro | $31.00 | $180.00 | - |\n'
            ),
            'lists gpt-7-pro at conflicting standard rates',
        ),
    ],
)
def test_openai_rejects_an_unexpected_pricing_page(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_openai.parse_pricing_markdown(markdown)


@pytest.mark.vcr()
def test_openai_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'openai.yml'
    copyfile(package_dir / 'providers/openai.yml', provider_path)

    source_openai.main(provider_path)

    assert capsys.readouterr().out == 'OpenAI prices updated: 0 added, 46 updated\n'
