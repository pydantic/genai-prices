from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from prices import source_cursor
from prices.prices_types import ModelPrice, StartDateConstraint, Tier, TieredPrices
from prices.update import ProviderYaml

from .fixtures import ProviderSnapshot

PRICING_MARKDOWN = """\
# Models & Pricing

### Cursor models

| Model | Provider | Input | Cache write | Cache read | Output | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Grok 4.7 | Cursor | $2 | - | $0.5 | $6 | Long context |
| Grok 4.7 500k | Cursor | $4 | - | $1 | $12 | Long context |
| Grok 4.6 | Cursor | $2 | - | $0.5 | $6 | Jointly trained |
| Grok 4.6 (Fast) | Cursor | $4 | - | $1 | $12 | Jointly trained |
| Grok 4.5 | Cursor | $2 | - | $0.5 | $6 | Jointly trained |
| Grok 4.5 (Fast) | Cursor | $4 | - | $1 | $18 | Jointly trained |
| [Composer 2.5](https://cursor.com/blog/composer-2-5) | Cursor | $0.5 | - | $0.2 | $2.5 | - |
| [Composer 2.5 (Fast)](https://cursor.com/blog/composer-2-5) | Cursor | $3 | - | $0.5 | $15 | - |

## Other Models

| Ignored | Other | $1 | - | $0.1 | $2 | - |
"""


def test_parse_pricing_markdown_extracts_cursor_models() -> None:
    models = source_cursor.parse_pricing_markdown(PRICING_MARKDOWN)

    assert [model.id for model in models] == [
        'grok-4.7',
        'grok-4.6',
        'grok-4.6-fast',
        'grok-4.5',
        'grok-4.5-fast',
        'composer-2.5',
        'composer-2.5-fast',
    ]
    assert models[1].prices == ModelPrice(
        input_mtok=Decimal('2'), cache_read_mtok=Decimal('0.5'), output_mtok=Decimal('6')
    )
    assert models[-1].name == 'Composer 2.5 Fast'
    assert models[-1].prices == ModelPrice(
        input_mtok=Decimal('3'), cache_read_mtok=Decimal('0.5'), output_mtok=Decimal('15')
    )
    assert all(model.prices_checked == date.today() for model in models)


def test_parse_pricing_markdown_returns_empty_without_cursor_section() -> None:
    assert source_cursor.parse_pricing_markdown('# Models & Pricing\n') == []


def test_parse_pricing_markdown_folds_500k_rows_into_long_context_tiers() -> None:
    [model] = source_cursor.parse_pricing_markdown(PRICING_MARKDOWN)[:1]

    assert model.prices == ModelPrice(
        input_mtok=TieredPrices(base=Decimal('2'), tiers=[Tier(start=256_000, price=Decimal('4'))]),
        cache_read_mtok=TieredPrices(base=Decimal('0.5'), tiers=[Tier(start=256_000, price=Decimal('1'))]),
        output_mtok=TieredPrices(base=Decimal('6'), tiers=[Tier(start=256_000, price=Decimal('12'))]),
    )


@pytest.mark.parametrize(
    ('markdown', 'note', 'model_ids'),
    [
        (
            PRICING_MARKDOWN.replace('Grok 4.5 |', 'Grok 4.6 |', 1),
            'Cursor: kept grok-4.6 unchanged, the pricing page lists grok-4.6 more than once; update it by hand\n',
            ['grok-4.7', 'grok-4.6-fast', 'grok-4.5-fast', 'composer-2.5', 'composer-2.5-fast'],
        ),
        (
            PRICING_MARKDOWN.replace(
                '| Grok 4.6 |', '| Grok 4.7 500k | Cursor | $5 | - | $1 | $15 | Long context |\n| Grok 4.6 |', 1
            ),
            'Cursor: kept grok-4.7 unchanged, the pricing page lists grok-4.7-500k more than once; update it by hand\n',
            ['grok-4.6', 'grok-4.6-fast', 'grok-4.5', 'grok-4.5-fast', 'composer-2.5', 'composer-2.5-fast'],
        ),
    ],
)
def test_parse_pricing_markdown_reports_a_duplicate_model_and_reads_the_others(
    markdown: str, note: str, model_ids: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    models = source_cursor.parse_pricing_markdown(markdown)

    assert [model.id for model in models] == model_ids
    assert capsys.readouterr().out == note


UNREADABLE_GROK_4_6 = '| Grok 4.6 | Cursor | Contact sales | - | $0.5 | $6 | Jointly trained |'


@pytest.mark.parametrize(
    ('markdown', 'note', 'model_ids'),
    [
        (
            PRICING_MARKDOWN.replace('| Grok 4.6 | Cursor | $2 |', '| Grok 4.6 | Cursor | Contact sales |'),
            "Cursor: skipped a row it cannot read for grok-4.6; update it by hand. Unexpected Cursor price 'Contact "
            f"sales' in row: {UNREADABLE_GROK_4_6}\n",
            ['grok-4.7', 'grok-4.6-fast', 'grok-4.5', 'grok-4.5-fast', 'composer-2.5', 'composer-2.5-fast'],
        ),
        (
            # A readable row after an unreadable one for the same model still leaves the model unchanged.
            PRICING_MARKDOWN.replace('| Grok 4.6 |', f'{UNREADABLE_GROK_4_6}\n| Grok 4.6 |', 1),
            "Cursor: skipped a row it cannot read for grok-4.6; update it by hand. Unexpected Cursor price 'Contact "
            f"sales' in row: {UNREADABLE_GROK_4_6}\n",
            ['grok-4.7', 'grok-4.6-fast', 'grok-4.5', 'grok-4.5-fast', 'composer-2.5', 'composer-2.5-fast'],
        ),
        (
            # An unreadable long-context row leaves its model unchanged rather than priced without the tier.
            PRICING_MARKDOWN.replace('| Grok 4.7 500k | Cursor | $4 |', '| Grok 4.7 500k | Cursor | TBD |'),
            "Cursor: skipped a row it cannot read for grok-4.7-500k; update it by hand. Unexpected Cursor price 'TBD' "
            'in row: | Grok 4.7 500k | Cursor | TBD | - | $1 | $12 | Long context |\n',
            ['grok-4.6', 'grok-4.6-fast', 'grok-4.5', 'grok-4.5-fast', 'composer-2.5', 'composer-2.5-fast'],
        ),
    ],
)
def test_parse_pricing_markdown_reports_an_unreadable_price_and_reads_the_others(
    markdown: str, note: str, model_ids: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    models = source_cursor.parse_pricing_markdown(markdown)

    assert [model.id for model in models] == model_ids
    assert capsys.readouterr().out == note


def test_cursor_updater_preserves_existing_metadata(tmp_path: Path) -> None:
    provider_path = tmp_path / 'cursor.yml'
    provider_path.write_text(
        """\
id: cursor
name: Cursor
api_pattern: cursor
models:
  - id: grok-4.6
    name: Curated name
    description: Curated description
    match:
      or:
        - equals: grok-4.6
        - regex: '^grok-4\\.6\\[fast=false\\]$'
    context_window: 256000
    deprecated: true
    price_discrepancies: {source: old}
    prices:
      - prices: {input_mtok: 8}
      - constraint: {start_date: 2025-01-01}
        prices: {input_mtok: 9}
"""
    )
    model = source_cursor.parse_pricing_markdown(PRICING_MARKDOWN)[1]

    assert ProviderYaml(provider_path).upsert_models([model], source='Cursor pricing', min_count=1) == (0, 1)

    updated = ProviderYaml(provider_path).provider.find_model('grok-4.6')
    assert updated is not None
    assert updated.name == 'Curated name'
    assert updated.description == 'Curated description'
    assert updated.context_window == 256000
    assert updated.deprecated is True
    assert updated.price_discrepancies is None
    assert isinstance(updated.prices, list)
    assert len(updated.prices) == 3
    constraint = updated.prices[-1].constraint
    assert isinstance(constraint, StartDateConstraint)
    assert constraint.start_date == date.today()
    assert updated.prices[-1].prices == ModelPrice(
        input_mtok=Decimal('2'), cache_read_mtok=Decimal('0.5'), output_mtok=Decimal('6')
    )

    ProviderYaml(provider_path).upsert_models([model], source='Cursor pricing', min_count=1)
    updated = ProviderYaml(provider_path).provider.find_model('grok-4.6')
    assert updated is not None
    assert isinstance(updated.prices, list)
    assert len(updated.prices) == 3


def test_cursor_updater_adds_new_models(tmp_path: Path) -> None:
    provider_path = tmp_path / 'cursor.yml'
    provider_path.write_text('id: cursor\nname: Cursor\napi_pattern: cursor\nmodels: []\n')
    model = source_cursor.parse_pricing_markdown(PRICING_MARKDOWN)[1]

    assert ProviderYaml(provider_path).upsert_models([model], source='Cursor pricing', min_count=1) == (1, 0)
    assert ProviderYaml(provider_path).provider.find_model('grok-4.6') is not None


@pytest.mark.vcr()
def test_cursor_main_fetches_recorded_pricing_page(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('cursor.yml')

    source_cursor.main(provider_path)

    assert capsys.readouterr().out == 'Cursor prices updated: 0 added, 8 updated\n'
