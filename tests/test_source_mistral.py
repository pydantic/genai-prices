from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_mistral
from prices.prices_types import ModelPrice
from prices.utils import package_dir

PRICING_MARKDOWN = """\
# API pricing

| Model | API name | Price |
| --- | --- | --- |
| [Mistral Large 4](/models/mistral-large-4-0) | `mistral-large-4` | Input $0.68 /M Tokens (sale price, regular $1.36)<br>Cached input $0.07 /M Tokens<br>Output $2.09 /M Tokens |
| [OCR 4.1](/models/ocr-4-1) | `mistral-ocr-4-1` | Input $4 /1000 Pages<br>Input $5 /1000 Annotated Pages |
| [Voxtral Mini Transcribe 2](/models/voxtral-mini-transcribe-26-02) | `voxtral-mini-2602` | Input $0.003 /Min |
| [Voxtral TTS](/models/voxtral-tts-26-03) | `voxtral-mini-tts-2603` | Input $0 /M Chars<br>Output $16 /M Chars |
| [Mistral Moderation 2](/models/mistral-moderation-26-03) | `mistral-moderation-2603` | Free<br>$0 /M Tokens |
"""


def test_mistral_parses_token_page_and_audio_rates_and_skips_unsupported_units() -> None:
    models = source_mistral.parse_pricing_markdown(PRICING_MARKDOWN)

    assert [(model.id, model.name, model.prices_checked) for model in models] == [
        ('mistral-large-4', 'Mistral Large 4', date.today()),
        ('mistral-ocr-4-1', 'OCR 4.1', date.today()),
        ('voxtral-mini-2602', 'Voxtral Mini Transcribe 2', date.today()),
    ]
    assert [model.prices for model in models] == [
        ModelPrice(input_mtok=Decimal('0.68'), cache_read_mtok=Decimal('0.07'), output_mtok=Decimal('2.09')),
        ModelPrice.model_validate({'input_document_kpages': 4, 'input_annotated_document_kpages': 5}),
        ModelPrice.model_validate({'audio_hours': '0.18', 'input_audio_hours': '0.18'}),
    ]


@pytest.mark.parametrize(
    ('markdown', 'error'),
    [
        ('| [Codestral](/models/codestral) | codestral | Input $0.3 /M Tokens |', 'Unexpected Mistral pricing row'),
        (
            '| [Codestral](/models/codestral) | `codestral` | Input €0.3 /M Tokens |',
            "Unexpected Mistral price 'Input €0.3 /M Tokens'",
        ),
    ],
)
def test_mistral_rejects_unexpected_pricing_shapes(markdown: str, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        source_mistral.parse_pricing_markdown(markdown)


@pytest.mark.vcr()
def test_mistral_main_fetches_recorded_pricing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'mistral.yml'
    copyfile(package_dir / 'providers/mistral.yml', provider_path)

    source_mistral.main(provider_path)

    assert capsys.readouterr().out == 'Mistral prices updated: 0 added, 12 updated\n'
