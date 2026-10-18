from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_doubleword
from prices.prices_types import ModelPrice
from prices.utils import package_dir

CATALOG = """\
## Model Catalog

### Active Models

| Model | Realtime | Async | Batch (24h) |
|-------|----------|-------|-------------|
| [GLM 5.2](/inference-api/models/zai-org-glm-5-2-fp8) | \\$0.93 / \\$0.19 / \\$3.00 | \\$0.70 / \\$0.14 / \\$2.25 | \\$0.47 / \\$0.09 / \\$1.50 |
| [OCR](/inference-api/models/ocr) | — | \\$0.08 / \\$0.08 / \\$0.08 | \\$0.05 / \\$0.05 / \\$0.05 |
| [Embedding](/inference-api/models/embedding) | \\$0.04 / \\$0.04 / \\$0.00 | \\$0.03 / \\$0.03 / \\$0.00 | \\$0.02 / \\$0.02 / \\$0.00 |

### Scheduled for Deprecation
"""

PAGES = {
    'https://docs.doubleword.ai/inference-api/models/zai-org-glm-5-2-fp8.md': (
        '  Max Total Tokens: 1048576\n'
        'Open this model in the [Playground](https://app.doubleword.ai/playground?model=zai-org%2FGLM-5.2-FP8&from=x).'
    ),
    'https://docs.doubleword.ai/inference-api/models/embedding.md': (
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
        ('Qwen/Qwen3-Embedding-8B', 'Embedding', None, ModelPrice(input_mtok=Decimal('0.04'))),
    ]
    assert models[0].prices_checked == date.today()


@pytest.mark.parametrize(
    'catalog, error',
    [
        (CATALOG.replace('| Async |', '| Flex |'), 'no Active Models table in the expected shape'),
        (CATALOG.replace('[OCR](/inference-api/models/ocr)', 'OCR'), 'Unexpected Doubleword models row'),
        (CATALOG.replace('\\$0.93 / \\$0.19', '\\$0.93'), 'Unexpected Doubleword Realtime price'),
    ],
)
def test_doubleword_rejects_unexpected_catalog_shapes(catalog: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_doubleword.parse_models(catalog, PAGES.__getitem__)


def test_doubleword_rejects_a_model_page_without_an_api_id() -> None:
    with pytest.raises(RuntimeError, match='has no playground model ID'):
        source_doubleword.parse_models(CATALOG, lambda url: 'no playground here')


@pytest.mark.vcr()
def test_doubleword_main_fetches_recorded_catalog(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'doubleword.yml'
    copyfile(package_dir / 'providers/doubleword.yml', provider_path)

    source_doubleword.main(provider_path)

    assert capsys.readouterr().out == 'Doubleword prices updated: 0 added, 15 updated\n'
