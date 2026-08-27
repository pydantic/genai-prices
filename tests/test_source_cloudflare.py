from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_cloudflare
from prices.prices_types import ModelPrice, StartDateConstraint
from prices.update import ProviderYaml
from prices.utils import package_dir

PRICING_MARKDOWN = """\
## LLM model pricing

| Model | Price in Tokens | Price in Neurons |
| --- | --- | --- |
| @cf/example/first | $0.100 per M input tokens  $0.020 per M cached input tokens  $0.300 per M output tokens | 1 |

## Embeddings model pricing

| Model | Price in Tokens | Price in Neurons |
| --- | --- | --- |
| @cf/example/embedding | $0.010 per M input tokens | 1 |

## Image model pricing

| @cf/example/image | $0.001 per 512x512 tile | 1 |

## Other model pricing

| Model | Price in Tokens | Price in Neurons |
| --- | --- | --- |
| @cf/example/classifier | $0.020 per M input tokens | 1 |
| @cf/example/images | $2.51 per M images | 1 |
"""


def test_parse_pricing_markdown_extracts_supported_token_prices() -> None:
    models = source_cloudflare.parse_pricing_markdown(PRICING_MARKDOWN)

    assert [model.id for model in models] == [
        '@cf/example/first',
        '@cf/example/embedding',
        '@cf/example/classifier',
    ]
    first_prices = models[0].prices
    assert isinstance(first_prices, ModelPrice)
    assert first_prices.input_mtok == Decimal('0.100')
    assert first_prices.cache_read_mtok == Decimal('0.020')
    assert first_prices.output_mtok == Decimal('0.300')
    assert models[0].prices_checked == date.today()


def test_parse_pricing_markdown_rejects_duplicate_models() -> None:
    duplicate = PRICING_MARKDOWN.replace('@cf/example/embedding', '@cf/example/first')

    with pytest.raises(RuntimeError, match='Duplicate Cloudflare model in pricing data: @cf/example/first'):
        source_cloudflare.parse_pricing_markdown(duplicate)


def test_cloudflare_updater_preserves_existing_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'cloudflare.yml'
    provider_path.write_text(
        """\
id: cloudflare
name: Cloudflare Workers AI
api_pattern: cloudflare
models:
  - id: '@cf/example/embedding'
    name: Existing embedding
    match: {equals: '@cf/example/embedding'}
    prices: {input_mtok: 9}

  - id: '@cf/example/first'
    name: Curated name
    match: {equals: '@cf/example/first'}
    deprecated: true
    price_discrepancies: {source: old}
    prices:
      - prices: {input_mtok: 8}
      - constraint: {start_date: 2025-01-01}
        prices: {input_mtok: 9}
"""
    )
    monkeypatch.setattr(source_cloudflare, 'MIN_MODEL_COUNT', 3)

    assert source_cloudflare.update_cloudflare_provider(
        ProviderYaml(provider_path), source_cloudflare.parse_pricing_markdown(PRICING_MARKDOWN)
    ) == (1, 2)

    provider = ProviderYaml(provider_path).provider
    assert [model.id for model in provider.models] == [
        '@cf/example/classifier',
        '@cf/example/embedding',
        '@cf/example/first',
    ]
    first = provider.find_model('@cf/example/first')
    assert first is not None
    assert first.name == 'Curated name'
    assert first.deprecated is True
    assert first.price_discrepancies is None
    assert first.prices_checked == date.today()
    assert isinstance(first.prices, list)
    assert first.prices[0].constraint is None
    assert first.prices[0].prices.input_mtok == Decimal('8')
    assert first.prices[1].prices.input_mtok == Decimal('9')
    constraint = first.prices[2].constraint
    assert isinstance(constraint, StartDateConstraint)
    assert constraint.start_date == date.today()
    assert first.prices[2].prices.input_mtok == Decimal('0.100')
    classifier = provider.find_model('@cf/example/classifier')
    assert classifier is not None
    assert classifier.prices_checked == date.today()

    source_cloudflare.update_cloudflare_provider(
        ProviderYaml(provider_path), source_cloudflare.parse_pricing_markdown(PRICING_MARKDOWN)
    )
    first = ProviderYaml(provider_path).provider.find_model('@cf/example/first')
    assert first is not None
    assert isinstance(first.prices, list)
    assert len(first.prices) == 3


@pytest.mark.vcr()
def test_cloudflare_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'cloudflare.yml'
    copyfile(package_dir / 'providers/cloudflare.yml', provider_path)

    source_cloudflare.main(provider_path)

    assert capsys.readouterr().out == 'Cloudflare prices updated: 0 added, 47 updated\n'


def test_cloudflare_updater_rejects_suspiciously_small_results(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'cloudflare.yml'
    provider_path.write_text('id: cloudflare\nname: Cloudflare\napi_pattern: cloudflare\nmodels: []\n')
    monkeypatch.setattr(source_cloudflare, 'MIN_MODEL_COUNT', 1)

    with pytest.raises(RuntimeError, match='returned only 0 token-priced models; expected at least 1'):
        source_cloudflare.update_cloudflare_provider(ProviderYaml(provider_path), [])
