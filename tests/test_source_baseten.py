from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_baseten
from prices.prices_types import ModelPrice, StartDateConstraint
from prices.update import ProviderYaml
from prices.utils import package_dir

CATALOG_MARKDOWN = """\
export const SupportedModelsTable = () => {
  const rows = [{
    model: "GLM 4.7",
    slug: "zai-org/GLM-4.7",
    context: 200,
    maxOutput: 200
  }, {
    model: "OpenAI GPT 120B",
    slug: "openai/gpt-oss-120b",
    context: 128,
    maxOutput: 128
  }];
};
"""
PRICING_PAGE = (
    r'\"__typename\":\"LibraryModelRecord\",\"tryModelApiLink\":'
    r'\"https://app.baseten.co/model-apis/glm-4-7\",\"perfCost\":0.6,'
    r'\"perfCostOutput\":2.2,\"perfCostCacheInput\":0.12}'
    r'\"__typename\":\"LibraryModelRecord\",\"tryModelApiLink\":'
    r'\"https://app.baseten.co/model-apis/openai/gpt-oss-120b\",\"perfCost\":0.1,'
    r'\"perfCostOutput\":0.5}'
)


def test_parse_models_joins_catalog_and_pricing() -> None:
    models = source_baseten.parse_models(CATALOG_MARKDOWN, PRICING_PAGE)

    assert [model.id for model in models] == ['zai-org/GLM-4.7', 'openai/gpt-oss-120b']
    assert models[0].context_window == 200_000
    assert models[0].prices == ModelPrice(
        input_mtok=Decimal('0.6'), cache_read_mtok=Decimal('0.12'), output_mtok=Decimal('2.2')
    )
    assert models[1].price_comments == 'The pricing table does not publish a separate cached-input rate for this model.'
    assert all(model.prices_checked == date.today() for model in models)


def test_parse_catalog_rejects_missing_table() -> None:
    with pytest.raises(RuntimeError, match='Baseten model catalog table was not found'):
        source_baseten.parse_catalog('# Model APIs')


def test_parse_catalog_rejects_duplicate_models() -> None:
    duplicate = CATALOG_MARKDOWN.replace('openai/gpt-oss-120b', 'zai-org/GLM-4.7')

    with pytest.raises(RuntimeError, match='Baseten model catalog contains duplicate model IDs'):
        source_baseten.parse_catalog(duplicate)


def test_parse_pricing_page_skips_incomplete_records() -> None:
    marker = r'\"__typename\":\"LibraryModelRecord\"'
    page = (
        marker + r',\"tryModelApiLink\":'
        r'\"https://app.baseten.co/model-apis/zai-org/incomplete\",\"perfCostOutput\":2}'
        + marker
        + PRICING_PAGE.rsplit(marker, 1)[-1]
    )

    assert source_baseten.parse_pricing_page(page) == {
        'openai/gpt-oss-120b': ModelPrice(input_mtok=Decimal('0.1'), output_mtok=Decimal('0.5'))
    }


def test_parse_pricing_page_rejects_duplicate_models() -> None:
    with pytest.raises(RuntimeError, match='Duplicate Baseten pricing model: zai-org/GLM-4.7'):
        source_baseten.parse_pricing_page(PRICING_PAGE + PRICING_PAGE)


def test_parse_models_rejects_catalog_mismatch() -> None:
    with pytest.raises(RuntimeError, match=r'missing prices=\[.openai/gpt-oss-120b.\], missing catalog=\[\]'):
        source_baseten.parse_models(
            CATALOG_MARKDOWN, PRICING_PAGE.rsplit(r'\"__typename\":\"LibraryModelRecord\"', 1)[0]
        )


def test_baseten_updater_preserves_existing_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'baseten.yml'
    provider_path.write_text(
        """\
id: baseten
name: Baseten
api_pattern: baseten
models:
  - id: zai-org/GLM-4.7
    name: Curated name
    description: Curated description
    match: {equals: zai-org/GLM-4.7}
    context_window: 123456
    deprecated: true
    price_discrepancies: {source: old}
    prices: {input_mtok: 9}
"""
    )
    monkeypatch.setattr(source_baseten, 'MIN_MODEL_COUNT', 1)
    [model] = source_baseten.parse_models(CATALOG_MARKDOWN, PRICING_PAGE)[:1]

    assert source_baseten.update_baseten_provider(ProviderYaml(provider_path), [model]) == (0, 1)

    updated = ProviderYaml(provider_path).provider.find_model('zai-org/GLM-4.7')
    assert updated is not None
    assert updated.name == 'Curated name'
    assert updated.description == 'Curated description'
    assert updated.context_window == 123456
    assert updated.deprecated is True
    assert updated.price_discrepancies is None
    assert isinstance(updated.prices, list)
    assert isinstance(updated.prices[-1].constraint, StartDateConstraint)
    assert updated.prices[-1].constraint.start_date == date.today()


def test_baseten_updater_adds_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'baseten.yml'
    provider_path.write_text('id: baseten\nname: Baseten\napi_pattern: baseten\nmodels: []\n')
    monkeypatch.setattr(source_baseten, 'MIN_MODEL_COUNT', 1)
    [model] = source_baseten.parse_models(CATALOG_MARKDOWN, PRICING_PAGE)[:1]

    assert source_baseten.update_baseten_provider(ProviderYaml(provider_path), [model]) == (1, 0)
    assert ProviderYaml(provider_path).provider.find_model(model.id) is not None


def test_baseten_updater_rejects_suspiciously_small_results(tmp_path: Path) -> None:
    provider_path = tmp_path / 'baseten.yml'
    provider_path.write_text('id: baseten\nname: Baseten\napi_pattern: baseten\nmodels: []\n')

    with pytest.raises(RuntimeError, match='Baseten sources returned only 0 models; expected at least 15'):
        source_baseten.update_baseten_provider(ProviderYaml(provider_path), [])


def test_baseten_updater_rejects_sharp_catalog_drop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'baseten.yml'
    provider_path.write_text(
        'id: baseten\nname: Baseten\napi_pattern: baseten\nmodels:\n'
        + ''.join(
            f'  - id: model-{index}\n    match: {{equals: model-{index}}}\n    prices: {{input_mtok: 1}}\n'
            for index in range(3)
        )
    )
    monkeypatch.setattr(source_baseten, 'MIN_MODEL_COUNT', 1)
    [model] = source_baseten.parse_models(CATALOG_MARKDOWN, PRICING_PAGE)[:1]

    with pytest.raises(RuntimeError, match='Baseten sources returned only 1 models; tracked provider has 3'):
        source_baseten.update_baseten_provider(ProviderYaml(provider_path), [model])


@pytest.mark.vcr()
def test_baseten_main_fetches_recorded_sources(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'baseten.yml'
    copyfile(package_dir / 'providers/baseten.yml', provider_path)

    source_baseten.main(provider_path)

    assert capsys.readouterr().out == 'Baseten prices updated: 0 added, 15 updated\n'
