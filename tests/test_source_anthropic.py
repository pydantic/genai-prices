from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_anthropic
from prices.prices_types import ModelPrice, Tier, TieredPrices
from prices.utils import package_dir

PRICING_MARKDOWN = """\
## Model pricing

| Model | Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens |
| :---- | :---------------- | :-------------- | :-------------- | :----------------------- | :------------ |
| Claude Fable 5.1 | $10 / MTok | $12.50 / MTok | $20 / MTok | $0.25 / MTok<sup>1</sup> | $50 / MTok |
| Claude Mythos 5.1 ([limited availability](https://support.claude.com/en/articles/14604842)) | $10 / MTok | $12.50 / MTok | $20 / MTok | $0.25 / MTok | $50 / MTok |
| Claude Opus 4 ([retired, except on Google Cloud](https://platform.claude.com/docs/en/about-claude/model-deprecations)) | $15 / MTok | $18.75 / MTok | $30 / MTok | $1.50 / MTok | $75 / MTok |
| Claude Haiku 5.5 (for prompts up to 100,000 tokens) | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |
| Claude Haiku 5.5 (for prompts over 100,000 tokens) | $0.50 / MTok | $0.625 / MTok | $1 / MTok | $0.05 / MTok | $2.50 / MTok |
| Claude Haiku 3.5 | $0.80 / MTok | $1 / MTok | $1.60 / MTok | $0.08 / MTok | $4 / MTok |

## Cloud platform pricing
"""


def test_anthropic_parses_model_ids_cache_writes_and_long_prompt_tiers() -> None:
    fable, opus, haiku, haiku_3_5 = source_anthropic.parse_pricing_markdown(PRICING_MARKDOWN)

    assert (fable.id, fable.prices_checked) == ('claude-fable-5-1', date.today())
    assert fable.prices == ModelPrice.model_validate(
        {
            'input_mtok': Decimal('10'),
            'cache_write_mtok': Decimal('12.50'),
            'cache_write_1h_mtok': Decimal('20'),
            'cache_read_mtok': Decimal('0.25'),
            'output_mtok': Decimal('50'),
        }
    )
    assert (opus.id, haiku_3_5.id) == ('claude-opus-4-0', 'claude-3-5-haiku-latest')

    def tiered(base: str, price: str) -> TieredPrices:
        return TieredPrices(base=Decimal(base), tiers=[Tier(start=100_000, price=Decimal(price))])

    assert haiku.id == 'claude-haiku-5-5'
    assert haiku.prices == ModelPrice.model_validate(
        {
            'input_mtok': tiered('0.10', '0.50'),
            'cache_write_mtok': tiered('0.125', '0.625'),
            'cache_write_1h_mtok': tiered('0.20', '1'),
            'cache_read_mtok': tiered('0.01', '0.05'),
            'output_mtok': tiered('0.50', '2.50'),
        }
    )


HAIKU_UP_TO = '| Claude Haiku 5.5 (for prompts up to 100,000 tokens) |'
HAIKU_OVER = '| Claude Haiku 5.5 (for prompts over 100,000 tokens) |'


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        ('# Pricing\n', 'Anthropic pricing page has no model pricing table'),
        (PRICING_MARKDOWN.replace('| Claude Haiku 3.5 |', '| Haiku 3.5 |'), 'Unexpected Anthropic pricing row'),
        (PRICING_MARKDOWN.replace('| $1.60 / MTok |', '|'), 'Unexpected Anthropic pricing row'),
        (PRICING_MARKDOWN.replace('$0.80 / MTok', 'N/A'), "Unexpected Anthropic price 'N/A'"),
        (PRICING_MARKDOWN.replace('Claude Haiku 3.5', 'Claude Fable 5.1'), 'Duplicate Anthropic pricing row'),
        (
            PRICING_MARKDOWN.replace('over 100,000', 'over 200,000'),
            'claude-haiku-5-5 do not pair a base and a long-context rate',
        ),
        (
            PRICING_MARKDOWN.replace(HAIKU_UP_TO, '| Claude Haiku 5 (for prompts up to 100,000 tokens) |'),
            'claude-haiku-5 do not pair a base and a long-context rate',
        ),
        (
            PRICING_MARKDOWN.replace(HAIKU_UP_TO, '| Claude Haiku 5 |'),
            'Anthropic long-context rows without a base row: claude-haiku-5-5',
        ),
        (PRICING_MARKDOWN.replace(HAIKU_OVER, HAIKU_UP_TO), 'Duplicate Anthropic pricing row'),
    ],
)
def test_anthropic_rejects_an_unexpected_pricing_table(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_anthropic.parse_pricing_markdown(markdown)


@pytest.mark.vcr()
def test_anthropic_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'anthropic.yml'
    copyfile(package_dir / 'providers/anthropic.yml', provider_path)

    source_anthropic.main(provider_path)

    assert capsys.readouterr().out == 'Anthropic prices updated: 0 added, 18 updated\n'
