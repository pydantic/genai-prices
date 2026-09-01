from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_cursor
from prices.prices_types import ModelPrice, StartDateConstraint
from prices.update import ProviderYaml
from prices.utils import package_dir

PRICING_MARKDOWN = """\
# Models & Pricing

## Cursor Models

| Model | Provider | Input | Cache write | Cache read | Output | Notes |
| --- | --- | --- | --- | --- | --- | --- |
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
        'grok-4.6',
        'grok-4.6-fast',
        'grok-4.5',
        'grok-4.5-fast',
        'composer-2.5',
        'composer-2.5-fast',
    ]
    assert models[0].prices == ModelPrice(
        input_mtok=Decimal('2'), cache_read_mtok=Decimal('0.5'), output_mtok=Decimal('6')
    )
    assert models[-1].name == 'Composer 2.5 Fast'
    assert models[-1].prices == ModelPrice(
        input_mtok=Decimal('3'), cache_read_mtok=Decimal('0.5'), output_mtok=Decimal('15')
    )
    assert all(model.prices_checked == date.today() for model in models)


def test_parse_pricing_markdown_returns_empty_without_cursor_section() -> None:
    assert source_cursor.parse_pricing_markdown('# Models & Pricing\n') == []


def test_parse_pricing_markdown_rejects_unknown_models() -> None:
    markdown = PRICING_MARKDOWN.replace('Grok 4.6 |', 'Unknown |', 1)

    with pytest.raises(RuntimeError, match='Unknown Cursor model in pricing data: Unknown'):
        source_cursor.parse_pricing_markdown(markdown)


def test_parse_pricing_markdown_rejects_duplicate_models() -> None:
    markdown = PRICING_MARKDOWN.replace('Grok 4.5 |', 'Grok 4.6 |', 1)

    with pytest.raises(RuntimeError, match='Duplicate Cursor model in pricing data: grok-4.6'):
        source_cursor.parse_pricing_markdown(markdown)


def test_cursor_updater_preserves_existing_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr(source_cursor, 'MIN_MODEL_COUNT', 1)
    [model] = source_cursor.parse_pricing_markdown(PRICING_MARKDOWN)[:1]

    assert source_cursor.update_cursor_provider(ProviderYaml(provider_path), [model]) == (0, 1)

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

    source_cursor.update_cursor_provider(ProviderYaml(provider_path), [model])
    updated = ProviderYaml(provider_path).provider.find_model('grok-4.6')
    assert updated is not None
    assert isinstance(updated.prices, list)
    assert len(updated.prices) == 3


def test_cursor_updater_adds_new_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'cursor.yml'
    provider_path.write_text('id: cursor\nname: Cursor\napi_pattern: cursor\nmodels: []\n')
    monkeypatch.setattr(source_cursor, 'MIN_MODEL_COUNT', 1)
    [model] = source_cursor.parse_pricing_markdown(PRICING_MARKDOWN)[:1]

    assert source_cursor.update_cursor_provider(ProviderYaml(provider_path), [model]) == (1, 0)
    assert ProviderYaml(provider_path).provider.find_model('grok-4.6') is not None


def test_cursor_updater_rejects_suspiciously_small_results(tmp_path: Path) -> None:
    provider_path = tmp_path / 'cursor.yml'
    provider_path.write_text('id: cursor\nname: Cursor\napi_pattern: cursor\nmodels: []\n')

    with pytest.raises(RuntimeError, match='Cursor pricing returned only 0 models; expected at least 6'):
        source_cursor.update_cursor_provider(ProviderYaml(provider_path), [])


@pytest.mark.vcr()
def test_cursor_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'cursor.yml'
    copyfile(package_dir / 'providers/cursor.yml', provider_path)

    source_cursor.main(provider_path)

    assert capsys.readouterr().out == 'Cursor prices updated: 0 added, 6 updated\n'
