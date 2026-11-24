from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from prices import source_baseten
from prices.prices_types import ModelPrice, StartDateConstraint
from prices.update import ProviderYaml

CATALOG_PAGE = (
    'const SupportedModelsTable=()=>{const rows=[{model:`GLM 4.7`,slug:`zai-org/GLM-4.7`,context:200,maxOutput:200},'
    '{model:`OpenAI GPT 120B`,slug:`openai/gpt-oss-120b`,context:128,maxOutput:128}];'
)
GLM_ROW = r'[\"GLM-4.7\",\"$$0.60\",\"$$0.12\",\"$$2.20\"]'
GPT_ROW = r'[\"GPT OSS 120B\",\"$$0.10\",\"—\",\"$$0.50\"]'


def pricing_page(*rows: str) -> str:
    return r'\"columns\":[\"Model\",\"Input\",\"Cache input\",\"Output\"],\"rows\":[' + ','.join(rows) + ']]}]'


PRICING_PAGE = pricing_page(GLM_ROW, GPT_ROW)


def test_parse_models_joins_catalog_and_pricing() -> None:
    models = source_baseten.parse_models(CATALOG_PAGE, PRICING_PAGE)

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


def test_parse_catalog_reports_a_duplicate_model_and_reads_the_others(capsys: pytest.CaptureFixture[str]) -> None:
    duplicate = CATALOG_PAGE.replace(
        'const rows=[', 'const rows=[{model:`GLM 4.7`,slug:`zai-org/GLM-4.7`,context:200,maxOutput:200},'
    )

    assert [model.id for model in source_baseten.parse_catalog(duplicate)] == ['openai/gpt-oss-120b']
    assert capsys.readouterr().out == (
        'Baseten: kept zai-org/GLM-4.7 unchanged, the model catalog lists it more than once; update it by hand\n'
    )


def test_parse_models_ignores_rows_outside_the_catalog() -> None:
    page = pricing_page(GLM_ROW, r'[\"elephant-1\",\"$$0.035\",\"$$0.00\",\"$$0.00\"]')

    assert [model.id for model in source_baseten.parse_models(CATALOG_PAGE, page)] == ['zai-org/GLM-4.7']


def test_parse_models_reports_a_free_rate_on_a_catalog_model(capsys: pytest.CaptureFixture[str]) -> None:
    page = pricing_page(GLM_ROW.replace('$$0.12', '$$0.00'), GPT_ROW)

    assert [model.id for model in source_baseten.parse_models(CATALOG_PAGE, page)] == ['openai/gpt-oss-120b']
    assert capsys.readouterr().out == (
        'Baseten lists a $0.00 rate for zai-org/GLM-4.7; record the free rate by hand\n'
        "Skipping Baseten models without published prices: ['zai-org/GLM-4.7']\n"
    )


def test_parse_pricing_page_rejects_a_page_without_the_token_table() -> None:
    with pytest.raises(RuntimeError, match='Baseten token pricing table was not found'):
        source_baseten.parse_pricing_page('<html></html>')


def test_parse_models_reports_an_unreadable_row_and_reads_the_others(capsys: pytest.CaptureFixture[str]) -> None:
    page = pricing_page(GLM_ROW.replace('$$2.20', 'Contact us'), GPT_ROW)

    assert [model.id for model in source_baseten.parse_models(CATALOG_PAGE, page)] == ['openai/gpt-oss-120b']
    assert capsys.readouterr().out == (
        'Baseten: skipped a row it cannot read for zai-org/GLM-4.7; update it by hand. '
        'Unexpected Baseten price: Contact us\n'
        "Skipping Baseten models without published prices: ['zai-org/GLM-4.7']\n"
    )


@pytest.mark.parametrize(
    'skipped_row',
    [GLM_ROW.replace('$$2.20', 'Contact us'), GLM_ROW.replace('$$0.12', '$$0.00')],
    ids=['unreadable', 'free rate'],
)
@pytest.mark.parametrize('skipped_first', [True, False], ids=['skipped first', 'readable first'])
def test_parse_models_keeps_a_model_unchanged_when_one_of_its_rows_is_skipped(
    skipped_row: str, skipped_first: bool
) -> None:
    rows = (skipped_row, GLM_ROW) if skipped_first else (GLM_ROW, skipped_row)

    models = source_baseten.parse_models(CATALOG_PAGE, pricing_page(*rows, GPT_ROW))

    assert [model.id for model in models] == ['openai/gpt-oss-120b']


def test_parse_models_reports_a_duplicate_model_and_reads_the_others(capsys: pytest.CaptureFixture[str]) -> None:
    page = pricing_page(GLM_ROW, GLM_ROW.replace('GLM-4.7', 'GLM 4.7'), GPT_ROW)

    assert [model.id for model in source_baseten.parse_models(CATALOG_PAGE, page)] == ['openai/gpt-oss-120b']
    assert capsys.readouterr().out == (
        'Baseten: kept zai-org/GLM-4.7 unchanged, the pricing page lists it more than once; update it by hand\n'
    )


def test_parse_models_skips_catalog_models_without_prices(capsys: pytest.CaptureFixture[str]) -> None:
    models = source_baseten.parse_models(CATALOG_PAGE, pricing_page(GLM_ROW))

    assert [model.id for model in models] == ['zai-org/GLM-4.7']
    assert capsys.readouterr().out == "Skipping Baseten models without published prices: ['openai/gpt-oss-120b']\n"


def test_baseten_updater_preserves_existing_metadata(tmp_path: Path) -> None:
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
    [model] = source_baseten.parse_models(CATALOG_PAGE, PRICING_PAGE)[:1]

    assert ProviderYaml(provider_path).upsert_models([model], source='Baseten sources', min_count=1) == (0, 1)

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


def test_baseten_updater_adds_models(tmp_path: Path) -> None:
    provider_path = tmp_path / 'baseten.yml'
    provider_path.write_text('id: baseten\nname: Baseten\napi_pattern: baseten\nmodels: []\n')
    [model] = source_baseten.parse_models(CATALOG_PAGE, PRICING_PAGE)[:1]

    assert ProviderYaml(provider_path).upsert_models([model], source='Baseten sources', min_count=1) == (1, 0)
    assert ProviderYaml(provider_path).provider.find_model(model.id) is not None


@pytest.mark.vcr()
def test_baseten_main_fetches_recorded_sources(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'baseten.yml'
    provider_path.write_text('id: baseten\nname: Baseten\napi_pattern: baseten\nmodels: []\n')

    source_baseten.main(provider_path)

    assert capsys.readouterr().out == (
        "Skipping Baseten models without published prices: ['deepseek-ai/DeepSeek-V4.1-Flash-1017-Fast']\n"
        'Baseten prices updated: 16 added, 0 updated\n'
    )
