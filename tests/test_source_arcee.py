from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_arcee
from prices.prices_types import ModelPrice, StartDateConstraint
from prices.update import ProviderYaml
from prices.utils import package_dir

PRICING_MARKDOWN = """\
# Pricing

#### Text Models

Prices per 1M Tokens.

<table><thead><tr><th>Model Name</th><th>Input</th><th>Output</th><th>Cached</th></tr></thead><tbody><tr><td>deepseek/deepseek-v4-flash-latest</td><td>$0.14</td><td>$0.28</td><td>$0.028</td></tr><tr><td>deepseek/deepseek-v4-pro</td><td>$1.74</td><td>$3.48</td><td>$0.20</td></tr><tr><td>moonshotai/kimi-k3</td><td>$3.00</td><td>$15.00</td><td>$0.30</td></tr><tr><td>thinkingmachines/inkling-small</td><td>$0.50</td><td>$1.20</td><td>$0.10</td></tr><tr><td>trinity-large-thinking</td><td>$0.25</td><td>$0.80</td><td>$0.06</td></tr><tr><td>zai-org/glm-5.2</td><td>$1.40</td><td>$4.40</td><td>$0.26</td></tr></tbody></table>
"""


def test_parse_pricing_markdown_extracts_arcee_models() -> None:
    models = source_arcee.parse_pricing_markdown(PRICING_MARKDOWN)

    assert [model.id for model in models] == [
        'deepseek/deepseek-v4-flash-latest',
        'deepseek/deepseek-v4-pro',
        'moonshotai/kimi-k3',
        'thinkingmachines/inkling-small',
        'trinity-large-thinking',
        'zai-org/glm-5.2',
    ]
    assert models[0].name == 'DeepSeek V4 Flash'
    assert models[0].prices == ModelPrice(
        input_mtok=Decimal('0.14'), cache_read_mtok=Decimal('0.028'), output_mtok=Decimal('0.28')
    )
    assert all(model.prices_checked == date.today() for model in models)


def test_parse_pricing_markdown_returns_empty_without_text_models() -> None:
    assert source_arcee.parse_pricing_markdown('# Pricing\n') == []


def test_parse_pricing_markdown_rejects_duplicate_models() -> None:
    duplicate = PRICING_MARKDOWN.replace('deepseek/deepseek-v4-pro', 'deepseek/deepseek-v4-flash-latest')

    with pytest.raises(RuntimeError, match='Duplicate Arcee model in pricing data: deepseek/deepseek-v4-flash-latest'):
        source_arcee.parse_pricing_markdown(duplicate)


def test_parse_pricing_markdown_rejects_invalid_prices() -> None:
    invalid = PRICING_MARKDOWN.replace('$0.14', 'Contact Sales')

    with pytest.raises(RuntimeError, match='Invalid Arcee price: Contact Sales'):
        source_arcee.parse_pricing_markdown(invalid)


def test_parse_pricing_markdown_accepts_unpriced_units() -> None:
    unpriced = PRICING_MARKDOWN.replace('$0.028', '-', 1)

    [model] = source_arcee.parse_pricing_markdown(unpriced)[:1]

    assert model.prices == ModelPrice(input_mtok=Decimal('0.14'), output_mtok=Decimal('0.28'))


def test_arcee_updater_preserves_existing_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'arcee.yml'
    provider_path.write_text(
        """\
id: arcee
name: Arcee
api_pattern: arcee
models:
  - id: deepseek/deepseek-v4-flash-latest
    name: Curated name
    description: Curated description
    match: {equals: deepseek/deepseek-v4-flash-latest}
    context_window: 123456
    deprecated: true
    price_discrepancies: {source: old}
    prices:
      - prices: {input_mtok: 8}
      - constraint: {start_date: 2025-01-01}
        prices: {input_mtok: 9}
"""
    )
    monkeypatch.setattr(source_arcee, 'MIN_MODEL_COUNT', 1)
    [model] = source_arcee.parse_pricing_markdown(PRICING_MARKDOWN)[:1]

    assert source_arcee.update_arcee_provider(ProviderYaml(provider_path), [model]) == (0, 1)

    updated = ProviderYaml(provider_path).provider.find_model('deepseek/deepseek-v4-flash-latest')
    assert updated is not None
    assert updated.name == 'Curated name'
    assert updated.description == 'Curated description'
    assert updated.context_window == 123456
    assert updated.deprecated is True
    assert updated.price_discrepancies is None
    assert isinstance(updated.prices, list)
    assert len(updated.prices) == 3
    constraint = updated.prices[-1].constraint
    assert isinstance(constraint, StartDateConstraint)
    assert constraint.start_date == date.today()
    assert updated.prices[-1].prices == model.prices

    source_arcee.update_arcee_provider(ProviderYaml(provider_path), [model])
    updated = ProviderYaml(provider_path).provider.find_model('deepseek/deepseek-v4-flash-latest')
    assert updated is not None
    assert isinstance(updated.prices, list)
    assert len(updated.prices) == 3


def test_arcee_updater_adds_new_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'arcee.yml'
    provider_path.write_text('id: arcee\nname: Arcee\napi_pattern: arcee\nmodels: []\n')
    monkeypatch.setattr(source_arcee, 'MIN_MODEL_COUNT', 1)
    [model] = source_arcee.parse_pricing_markdown(PRICING_MARKDOWN)[:1]

    assert source_arcee.update_arcee_provider(ProviderYaml(provider_path), [model]) == (1, 0)
    assert ProviderYaml(provider_path).provider.find_model(model.id) is not None


def test_arcee_updater_rejects_suspiciously_small_results(tmp_path: Path) -> None:
    provider_path = tmp_path / 'arcee.yml'
    provider_path.write_text('id: arcee\nname: Arcee\napi_pattern: arcee\nmodels: []\n')

    with pytest.raises(RuntimeError, match='Arcee pricing returned only 0 models; expected at least 6'):
        source_arcee.update_arcee_provider(ProviderYaml(provider_path), [])


def test_arcee_updater_rejects_sharp_catalog_drop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'arcee.yml'
    provider_path.write_text(
        'id: arcee\nname: Arcee\napi_pattern: arcee\nmodels:\n'
        + ''.join(
            f'  - id: model-{index}\n    name: Model {index}\n    match: {{equals: model-{index}}}\n    prices: {{input_mtok: 1}}\n'
            for index in range(3)
        )
    )
    monkeypatch.setattr(source_arcee, 'MIN_MODEL_COUNT', 1)
    [model] = source_arcee.parse_pricing_markdown(PRICING_MARKDOWN)[:1]

    with pytest.raises(RuntimeError, match='Arcee pricing returned only 1 models; tracked provider has 3'):
        source_arcee.update_arcee_provider(ProviderYaml(provider_path), [model])


@pytest.mark.vcr()
def test_arcee_main_fetches_recorded_pricing_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'arcee.yml'
    copyfile(package_dir / 'providers/arcee.yml', provider_path)

    source_arcee.main(provider_path)

    assert capsys.readouterr().out == 'Arcee prices updated: 0 added, 6 updated\n'
