from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_github_copilot
from prices.prices_types import ClauseEquals, ModelPrice, Tier, TieredPrices
from prices.utils import package_dir

HEADER = """\
| Model | Release status | Category | Tier | Threshold (input tokens) | Input | Cached input | Cache write | Output |
| ----- | -------------- | -------- | ---- | ------------------------ | ----: | -----------: | ----------: | -----: |
|       |                |          |      |                          |       |              |             |        |
"""
PRICING_MARKDOWN = f"""\
## Pricing tables

{HEADER}\
| GPT-5.4 | GA | Versatile | Default | ≤ 272K | $2.50 | $0.25 | Not applicable | $15.00 |
| GPT-5.4 | GA | Versatile | Long context | > 272K | $5.00 | $0.50 | Not applicable | $22.50 |
| Claude Opus 4.8 (fast mode) (preview) | GA | Powerful | Default | Not applicable | $10.00 | $1.00 | $12.50 | $50.00 |

| Model | Release status | Category | Input | Cached input | Output |
| ----- | -------------- | -------- | ----: | -----------: | -----: |
| Gemini 4 Argon[^gemini-4-argon-promo] | GA | Powerful | $2.00 | $0.10 | $10.00 |
"""


def test_copilot_parses_flat_tiered_and_renamed_models() -> None:
    models = source_github_copilot.parse_pricing_markdown(PRICING_MARKDOWN)

    assert [(model.id, model.name, model.match) for model in models] == [
        ('gpt-5.4', 'GPT-5.4', ClauseEquals(equals='gpt-5.4')),
        ('claude-opus-4.8-fast', 'Claude Opus 4.8 (fast mode)', ClauseEquals(equals='claude-opus-4.8-fast')),
        ('gemini-4-argon', 'Gemini 4 Argon', ClauseEquals(equals='gemini-4-argon')),
    ]
    assert models[0].prices == ModelPrice(
        input_mtok=TieredPrices(base=Decimal('2.50'), tiers=[Tier(start=272000, price=Decimal('5.00'))]),
        cache_read_mtok=TieredPrices(base=Decimal('0.25'), tiers=[Tier(start=272000, price=Decimal('0.50'))]),
        output_mtok=TieredPrices(base=Decimal('15.00'), tiers=[Tier(start=272000, price=Decimal('22.50'))]),
    )
    assert models[1].prices == ModelPrice(
        input_mtok=Decimal('10'),
        cache_read_mtok=Decimal('1'),
        cache_write_mtok=Decimal('12.5'),
        output_mtok=Decimal(50),
    )
    assert models[2].prices == ModelPrice(
        input_mtok=Decimal('2'), cache_read_mtok=Decimal('0.1'), output_mtok=Decimal('10')
    )
    assert models[2].prices_checked == date.today()


def row(model: str, tier: str, threshold: str, input_price: str = '$1.00', cache_write: str = '$1.25') -> str:
    return f'| {model} | GA | Versatile | {tier} | {threshold} | {input_price} | $0.10 | {cache_write} | $5.00 |\n'


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        ('| Model | Price |\n| - | - |\n| A | $1 |\n', r"Unexpected GitHub Copilot pricing columns: \['Price'\]"),
        (HEADER + row('Claude (beta)', 'Default', 'Not applicable'), 'Cannot map GitHub Copilot model name'),
        (HEADER + row('A', 'Default', '≤ 1K') * 2, 'Duplicate GitHub Copilot model in pricing data: a'),
        (HEADER + row('A', 'Batch', 'Not applicable'), 'Unexpected GitHub Copilot tier for a: Batch'),
        (HEADER + row('A', 'Long context', '> 1K'), 'long-context rates but no default rates: a'),
        (HEADER + row('A', 'Default', '≤ 1K') + row('A', 'Long context', '> 2K'), 'thresholds do not line up for a'),
        (
            HEADER + row('A', 'Default', '≤ 1K') + row('A', 'Long context', '> 1K', cache_write='Not applicable'),
            'long-context tier is missing cache_write_mtok for a',
        ),
        (HEADER + row('A', 'Default', 'Not applicable', input_price='1.00'), 'Unexpected GitHub Copilot price cell'),
        (HEADER + row('A', 'Default', '≤ 1M'), 'Unexpected GitHub Copilot threshold: ≤ 1M'),
        (HEADER + '| A | GA |\n', 'Table row has 2 cells, header has 9'),
    ],
)
def test_copilot_rejects_unexpected_pricing_rows(markdown: str, error: str) -> None:
    with pytest.raises((RuntimeError, ValueError), match=error):
        source_github_copilot.parse_pricing_markdown(markdown)


def test_copilot_refuses_to_guess_ids_for_unlisted_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'github_copilot.yml'
    copyfile(package_dir / 'providers/github_copilot.yml', provider_path)
    monkeypatch.setattr(
        source_github_copilot,
        'get_markdown',
        {source_github_copilot.PRICING_URL: HEADER + row('GPT-9 Nova', 'Default', 'Not applicable')}.get,
    )

    with pytest.raises(RuntimeError, match='lists models missing from the provider YAML: gpt-9-nova'):
        source_github_copilot.main(provider_path)


@pytest.mark.vcr()
def test_copilot_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'github_copilot.yml'
    copyfile(package_dir / 'providers/github_copilot.yml', provider_path)

    source_github_copilot.main(provider_path)

    assert capsys.readouterr().out == 'GitHub Copilot prices updated: 0 added, 33 updated\n'
