from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_together
from prices.prices_types import ModelPrice
from prices.utils import package_dir

MODELS_MARKDOWN = f"""\
## Chat models

{source_together.TABLE_HEADER}
| :- | :- | :- | :- | :- | :- | :- | :- | :- | :- |
| DeepSeek | DeepSeek V4.1 Flash | deepseek-ai/DeepSeek-V4.1-Flash | 1000000 | \\$0.30 | \\$0.006 | \\$1.20 | FP8 | Yes | Yes |
| Qwen | Qwen3.7 Max | Qwen/Qwen3.7-Max | - | \\$2.50 | - | \\$7.50 | - | Yes | Yes |
| Together AI | Tev1 4B | together/Tev1-4B | 32768 | \\$0.042 | - | Free | - | - | - |
| Prism ML | Bonsai 27B | Prism-ML/Bonsai-27B | 262144 | Free | - | Free | - | Yes | Yes |

**Chat model examples**

## Image models

| Organization | Model name | Model string for API | Unit | Price | Output per \\$1 |
| :- | :- | :- | :- | :- | :- |
| Black Forest Labs | Flux | black-forest-labs/FLUX | `megapixel` | \\$0.08 | 12 megapixels |
"""


def test_together_parses_chat_models_and_skips_free_ones() -> None:
    models = source_together.parse_models_markdown(MODELS_MARKDOWN)

    assert [(model.id, model.name, model.context_window) for model in models] == [
        ('deepseek-ai/DeepSeek-V4.1-Flash', 'DeepSeek V4.1 Flash', 1_000_000),
        ('Qwen/Qwen3.7-Max', 'Qwen3.7 Max', None),
        ('together/Tev1-4B', 'Tev1 4B', 32_768),
    ]
    assert [model.prices for model in models] == [
        ModelPrice(input_mtok=Decimal('0.30'), cache_read_mtok=Decimal('0.006'), output_mtok=Decimal('1.20')),
        ModelPrice(input_mtok=Decimal('2.50'), output_mtok=Decimal('7.50')),
        ModelPrice(input_mtok=Decimal('0.042')),
    ]
    assert models[0].prices_checked == date.today()


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        ('## Image models\n', 'no chat models table in the expected shape'),
        (MODELS_MARKDOWN.replace('| Structured outputs |', '|'), 'no chat models table in the expected shape'),
        (MODELS_MARKDOWN.replace('| FP8 | Yes | Yes |', '| FP8 |'), 'Unexpected Together chat model row'),
        (MODELS_MARKDOWN.replace('\\$1.20', '\\$1.20 per M'), "Unexpected Together price '"),
        (MODELS_MARKDOWN.replace('| 1000000 |', '| 1M |'), "Unexpected Together context length '1M'"),
    ],
)
def test_together_rejects_an_unexpected_models_page(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_together.parse_models_markdown(markdown)


@pytest.mark.vcr()
def test_together_main_fetches_recorded_models_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'together.yml'
    copyfile(package_dir / 'providers/together.yml', provider_path)

    source_together.main(provider_path)

    assert capsys.readouterr().out == 'Together prices updated: 0 added, 20 updated\n'
