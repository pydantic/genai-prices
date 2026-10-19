from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_groq
from prices.prices_types import ModelPrice
from prices.utils import package_dir

HEADER = '| ' + ' | '.join(source_groq.TABLE_HEADER) + ' |'
DIVIDER = '|' + ' --- |' * len(source_groq.TABLE_HEADER)
NO_VALUE = '\\-'


def row(model_id: str, name: str, price: str, context: str = '131,072') -> str:
    cell = f'[![Logo](https://console.groq.com/logo.png)  {name}](/docs/model/{model_id}){model_id}'
    return f'| {cell} | 500 | {price} | 250K TPM | {context} | 65,536 | \\- |'


MODELS_MARKDOWN = f"""\
## [Production Models](#production-models)

{HEADER}
{DIVIDER}
{row('llama-3.1-8b-instant', 'Llama 3.1 8B', 'ContactSales').replace('instant)', 'instant)Enterprise')}
{row('openai/gpt-oss-120b', 'GPT OSS 120B', '$0.15 input$0.60 output')}
{row('whisper-large-v3', 'Whisper', '$0.111 per hour', context=NO_VALUE)}

## [Preview Models](#preview-models)

{HEADER}
{DIVIDER}
{row('canopylabs/orpheus-v1-english', 'Orpheus V1 English', '$22.00 per 1M characters', context='4,000')}

## [Deprecated Models](#deprecated-models)
"""


def test_groq_parses_token_hourly_and_character_prices_and_skips_contact_sales_rows() -> None:
    models = source_groq.parse_models_markdown(MODELS_MARKDOWN)

    assert [(model.id, model.name, model.context_window) for model in models] == [
        ('openai/gpt-oss-120b', 'GPT OSS 120B', 131_072),
        ('whisper-large-v3', 'Whisper', None),
        ('canopylabs/orpheus-v1-english', 'Orpheus V1 English', 4_000),
    ]
    assert [model.prices for model in models] == [
        ModelPrice(input_mtok=Decimal('0.15'), output_mtok=Decimal('0.60')),
        ModelPrice.model_validate({'audio_hours': '0.111', 'input_audio_hours': '0.111'}),
        ModelPrice.model_validate({'input_mchars': '22.00'}),
    ]
    assert models[0].prices_checked == date.today()


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        (MODELS_MARKDOWN.split('## [Preview')[0], 'no Preview models table in the expected shape'),
        (MODELS_MARKDOWN.replace('| MAX FILE SIZE |', '|', 1), 'no Production models table in the expected shape'),
        (MODELS_MARKDOWN.replace('openai/gpt-oss-120b |', 'openai/gpt-oss-20b |'), 'Unexpected Groq model row'),
        (MODELS_MARKDOWN.replace('| 65,536 | \\- |', '|', 1), 'Unexpected Groq model row'),
        (
            MODELS_MARKDOWN.replace('$0.111 per hour', '$0.111 per minute'),
            "Unexpected Groq price '\\$0.111 per minute'",
        ),
    ],
)
def test_groq_rejects_an_unexpected_models_page(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_groq.parse_models_markdown(markdown)


@pytest.mark.vcr()
def test_groq_main_fetches_recorded_models_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'groq.yml'
    copyfile(package_dir / 'providers/groq.yml', provider_path)

    source_groq.main(provider_path)

    assert capsys.readouterr().out == 'Groq prices updated: 0 added, 10 updated\n'
