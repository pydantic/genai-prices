from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from prices import source_openai
from prices.prices_types import ClauseEquals, ModelPrice, Tier, TieredPrices

from .fixtures import ProviderSnapshot

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
| Cyber | gpt-cyber (short context) | $20.00 | $2.00 | $100.00 |
| Cyber | gpt-cyber (long context) | $40.00 | $4.00 | - |
| Cyber | gpt-cyber-preview (short context) | $12.50 | $1.25 | $75.00 |
| Cyber | gpt-cyber-preview (long context) | - | - | - |
"""


def tiered(base: str, price: str) -> TieredPrices:
    return TieredPrices(base=Decimal(base), tiers=[Tier(start=272_000, price=Decimal(price))])


def test_openai_parses_standard_text_rates_and_skips_other_tabs_and_units() -> None:
    models = source_openai.parse_pricing_markdown(PRICING_MARKDOWN)

    assert [(m.id, m.match, m.prices_checked) for m in models] == [
        (model_id, ClauseEquals(equals=model_id), date.today())
        for model_id in ('gpt-7', 'gpt-7-pro', 'gpt-bio', 'text-embedding-9', 'gpt-cyber', 'gpt-cyber-preview')
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
        # A long context row's blank output rate leaves the short context rate untiered.
        ModelPrice(input_mtok=tiered('20', '40'), cache_read_mtok=tiered('2', '4'), output_mtok=Decimal(100)),
        ModelPrice(input_mtok=Decimal('12.5'), cache_read_mtok=Decimal('1.25'), output_mtok=Decimal(75)),
    ]


def test_openai_rejects_a_page_without_a_standard_text_pricing_table() -> None:
    with pytest.raises(RuntimeError, match='OpenAI pricing page has no standard text pricing table'):
        source_openai.parse_pricing_markdown('# Pricing\n')


@pytest.mark.parametrize(
    ('markdown', 'error', 'model_id'),
    [
        (PRICING_MARKDOWN.replace('| gpt-bio |', '| GPT Bio |'), 'Unexpected OpenAI pricing row: ', 'gpt-bio'),
        (PRICING_MARKDOWN.replace('$25.00', 'TBD'), "Unexpected OpenAI price 'TBD' in row: ", 'gpt-bio'),
        (
            PRICING_MARKDOWN.replace('| $0.20 | $2.50 |', '| $0.20 | - |'),
            'OpenAI pricing row has a short or long context rate without its pair: ',
            'gpt-7',
        ),
        (
            PRICING_MARKDOWN.replace('| $0.40 | $5.00 |', '| $0.40 | - |'),
            'OpenAI pricing row has a short or long context rate without its pair: ',
            'gpt-7',
        ),
        (
            PRICING_MARKDOWN.replace('gpt-cyber-preview (long context) | - |', 'gpt-orphan (long context) | $1.00 |'),
            "OpenAI long context row has rates without a short context rate (['input_mtok']): ",
            None,
        ),
        (
            PRICING_MARKDOWN + '| Cyber | gpt-7 (long context) | $9.00 | - | - |\n',
            'OpenAI long context row repeats a tiered rate for input_mtok: ',
            'gpt-7',
        ),
        # An unreadable short or long context row keeps the model unchanged rather than dropping or misplacing its tier.
        (
            PRICING_MARKDOWN.replace('gpt-cyber (long context) | $40.00 |', 'gpt-cyber (long context) | TBD |'),
            "Unexpected OpenAI price 'TBD' in row: ",
            'gpt-cyber',
        ),
        (
            PRICING_MARKDOWN.replace('gpt-cyber (short context) | $20.00 |', 'gpt-cyber (short context) | TBD |'),
            "Unexpected OpenAI price 'TBD' in row: ",
            'gpt-cyber',
        ),
    ],
)
def test_openai_reports_an_unreadable_row_and_reads_the_others(
    markdown: str, error: str, model_id: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    models = source_openai.parse_pricing_markdown(markdown)

    expected = [model for model in source_openai.parse_pricing_markdown(PRICING_MARKDOWN) if model.id != model_id]
    assert models == expected
    [note] = capsys.readouterr().out.splitlines()
    assert note.startswith(f'OpenAI: skipped a row it cannot read; update it by hand. {error}')


def test_openai_skips_a_tier_named_only_by_its_heading() -> None:
    promotion = """
Ultrafast costs 3 times the Standard rate during the promotion.

### Ultrafast promotion pricing data

| Model | Input | Output | Cached input |
| --- | --- | --- | --- |
| gpt-bio | $15.00 | $75.00 | $1.50 |
"""

    models = source_openai.parse_pricing_markdown(
        PRICING_MARKDOWN.replace('\nStandard\n\n### Grouped', promotion + '\nStandard\n\n### Grouped')
    )

    assert models == source_openai.parse_pricing_markdown(PRICING_MARKDOWN)


@pytest.mark.parametrize(
    ('markdown', 'model_id'),
    [
        (
            PRICING_MARKDOWN.replace(
                '| gpt-7-pro | $30.00 | $180.00 | - |\n', '| gpt-7-pro | $31.00 | $180.00 | - |\n'
            ),
            'gpt-7-pro',
        ),
        (PRICING_MARKDOWN + '| Cyber | gpt-cyber (long context) | $41.00 | $4.00 | - |\n', 'gpt-cyber'),
        (
            PRICING_MARKDOWN.replace(
                '| Cyber | gpt-cyber (short context) |',
                '| Cyber | gpt-cyber (short context) | $20.00 | - | $100.00 |\n| Cyber | gpt-cyber (short context) |',
            ),
            'gpt-cyber',
        ),
    ],
)
def test_openai_keeps_a_model_listed_at_conflicting_rates_unchanged(
    markdown: str, model_id: str, capsys: pytest.CaptureFixture[str]
) -> None:
    models = source_openai.parse_pricing_markdown(markdown)

    expected = [model for model in source_openai.parse_pricing_markdown(PRICING_MARKDOWN) if model.id != model_id]
    assert models == expected
    assert capsys.readouterr().out == (
        f'OpenAI: kept {model_id} unchanged, the pricing page lists it at conflicting rates; update it by hand\n'
    )


@pytest.mark.vcr()
def test_openai_main_fetches_recorded_pricing_page(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('openai.yml')

    source_openai.main(provider_path)

    assert capsys.readouterr().out == 'OpenAI prices updated: 0 added, 46 updated\n'
