from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from prices import source_doubleword
from prices.prices_types import ModelPrice
from prices.update import ProviderYaml

from .fixtures import ProviderSnapshot

NEW_MODEL_IDS = (
    'Qwen/Qwen3.5-35B-A3B-FP8-dottxt',
    'deepseek-ai/DeepSeek-V4-Pro-0813',
    'meta-models/Muse-Glimmer-30B',
    'nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4',
    'zai-org/GLM-5.3',
    'zai-org/GLM-5.3-Flash',
)

CATALOG = """\
## Model Catalog

| Model | Realtime | Async | Batch (24h) |
|-------|----------|-------|-------------|
| [GLM 5.2](/inference-api/models/zai-org-glm-5-2-fp8) | \\$0.93 / \\$0.19 / \\$3.00 | \\$0.70 / \\$0.14 / \\$2.25 | \\$0.47 / \\$0.09 / \\$1.50 |
| [OCR](/inference-api/models/ocr) | — | \\$0.08 / \\$0.08 / \\$0.08 | \\$0.05 / \\$0.05 / \\$0.05 |
| [Embedding](/inference-api/models/embedding) | \\$0.04 / \\$0.04 / \\$0.00 | \\$0.03 / \\$0.03 / \\$0.00 | \\$0.02 / \\$0.02 / \\$0.00 |

## Retrieve model prices through the API
"""

PAGES = {
    'https://docs.doubleword.ai/inference-api/models/zai-org-glm-5-2-fp8.md': (
        '  Max Total Tokens: 1048576\n'
        'Open this model in the [Playground](https://app.doubleword.ai/playground?model=zai-org%2FGLM-5.2-FP8&from=x).'
    ),
    'https://docs.doubleword.ai/inference-api/models/embedding.md': (
        '**Max Total Tokens:** 32768\n'
        'Open this model in the [Playground](https://app.doubleword.ai/playground?model=Qwen%2FQwen3-Embedding-8B).'
    ),
}


def test_doubleword_parses_realtime_prices_and_api_ids_from_model_pages() -> None:
    models = source_doubleword.parse_models(CATALOG, PAGES.__getitem__)

    assert [(model.id, model.name, model.context_window, model.prices) for model in models] == [
        (
            'zai-org/GLM-5.2-FP8',
            'GLM 5.2',
            1048576,
            ModelPrice(input_mtok=Decimal('0.93'), cache_read_mtok=Decimal('0.19'), output_mtok=Decimal('3.00')),
        ),
        (
            'Qwen/Qwen3-Embedding-8B',
            'Embedding',
            32768,
            ModelPrice(input_mtok=Decimal('0.04')),
        ),
    ]
    assert models[0].prices_checked == date.today()


@pytest.mark.parametrize(
    'catalog, error',
    [
        (CATALOG.replace('| Async |', '| Flex |'), 'no model catalog table in the expected shape'),
    ],
)
def test_doubleword_rejects_unexpected_catalog_shapes(catalog: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_doubleword.parse_models(catalog, PAGES.__getitem__)


@pytest.mark.parametrize(
    'catalog, pages, error, model_ids',
    [
        (
            CATALOG.replace('[OCR](/inference-api/models/ocr)', 'OCR'),
            PAGES,
            'Unexpected Doubleword models row',
            ['zai-org/GLM-5.2-FP8', 'Qwen/Qwen3-Embedding-8B'],
        ),
        (
            CATALOG.replace('\\$0.93 / \\$0.19', '\\$0.93'),
            PAGES,
            'Unexpected Doubleword Realtime price for GLM 5.2: \\$0.93 / \\$3.00',
            ['Qwen/Qwen3-Embedding-8B'],
        ),
        (
            CATALOG,
            PAGES | {'https://docs.doubleword.ai/inference-api/models/embedding.md': 'no playground here'},
            'Doubleword model page /inference-api/models/embedding has no playground model ID',
            ['zai-org/GLM-5.2-FP8'],
        ),
    ],
)
def test_doubleword_reports_an_unreadable_row_and_reads_the_others(
    catalog: str, pages: dict[str, str], error: str, model_ids: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    models = source_doubleword.parse_models(catalog, pages.__getitem__)

    assert [model.id for model in models] == model_ids
    assert capsys.readouterr().out.startswith(f'Doubleword: skipped a row it cannot read; update it by hand. {error}')


@pytest.mark.vcr()
def test_doubleword_main_fetches_recorded_catalog(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('doubleword.yml')
    provider_yaml = ProviderYaml(provider_path)
    for model_id in NEW_MODEL_IDS:
        provider_yaml.remove_model(model_id)
    provider_yaml.save()

    source_doubleword.main(provider_path)

    assert capsys.readouterr().out == 'Doubleword prices updated: 6 added, 9 updated\n'
    provider = ProviderYaml(provider_path).provider
    glm = provider.find_model('zai-org/GLM-5.3')
    assert glm is not None
    assert glm.name == 'GLM 5.3'
    assert glm.prices == ModelPrice(
        input_mtok=Decimal('1.4'), cache_read_mtok=Decimal('0.28'), output_mtok=Decimal('4.4')
    )
    assert all(provider.find_model(model_id) is not None for model_id in NEW_MODEL_IDS)
