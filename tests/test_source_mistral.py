from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest

from prices import source_mistral
from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, StartDateConstraint, Tier, TieredPrices
from prices.update import ProviderYaml
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


def test_a_standard_rate_change_dates_new_variants_that_are_a_flat_share(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = tmp_path / 'mistral.yml'
    provider_path.write_text(
        """\
id: mistral
name: Mistral
api_pattern: mistral
models:
  - id: flat
    match: { equals: flat }
    prices: { input_mtok: 0.3, cache_read_mtok: 0.03, output_mtok: 0.9 }
    price_variants:
      - when: { processing: batch }
        constraint: { start_date: 2026-10-14 }
        prices: { input_mtok: 0.15, output_mtok: 0.45 }
      - when: { service_tier: priority }
        prices: { input_mtok: 0.6, cache_read_mtok: 0.06 }
      - when: { processing: batch }
        prices: { input_mtok: 1, output_mtok: 1 }
      - when: { service_tier: flex }
        prices: { cache_read_mtok: 0.015 }
      - when: { service_tier: default }
        prices: {}
  - id: tiered
    match: { equals: tiered }
    prices:
      input_mtok: { base: 2, tiers: [{ start: 200000, price: 4 }] }
      output_mtok: 8
    price_variants:
      - when: { processing: batch }
        prices:
          input_mtok: { base: 1, tiers: [{ start: 200000, price: 2 }] }
      - when: { service_tier: flex }
        prices:
          input_mtok: { base: 1, tiers: [{ start: 100000, price: 2 }] }
  - id: tiered-again
    match: { equals: tiered-again }
    prices:
      input_mtok: { base: 2, tiers: [{ start: 200000, price: 4 }] }
    price_variants:
      - when: { processing: batch }
        prices:
          input_mtok: { base: 1, tiers: [{ start: 200000, price: 2 }] }
  - id: uneven
    match: { equals: uneven }
    prices: { input_mtok: 1, output_mtok: 4 }
    price_variants:
      - when: { processing: batch }
        prices: { input_mtok: 0.5, output_mtok: 3 }
      - when: { service_tier: flex }
        prices: { input_mtok: 0.25, cache_read_mtok: 0.1 }
"""
    )
    today = date.today()

    def model(model_id: str, **prices: object) -> ModelInfo:
        return ModelInfo(
            id=model_id,
            match=ClauseEquals(equals=model_id),
            prices=ModelPrice.model_validate(prices),
            prices_checked=today,
        )

    models = [
        model('flat', input_mtok='0.4', cache_read_mtok='0.03', output_mtok='1.2'),
        model('tiered', input_mtok={'base': '3', 'tiers': [{'start': 200_000, 'price': '6'}]}),
        model('uneven', input_mtok='2'),
        model(
            'tiered-again',
            input_mtok={'base': '2', 'tiers': [{'start': 128_000, 'price': '3'}, {'start': 200_000, 'price': '4'}]},
        ),
    ]
    assert ProviderYaml(provider_path).upsert_models(models, source='Mistral', min_count=1) == (0, 4)

    provider = ProviderYaml(provider_path).provider
    flat = provider.find_model('flat')
    assert flat is not None and flat.price_variants is not None
    assert [(variant.when, variant.prices) for variant in flat.price_variants[:3]] == [
        ({'processing': 'batch'}, ModelPrice(input_mtok=Decimal('0.2'), output_mtok=Decimal('0.6'))),
        ({'processing': 'batch'}, ModelPrice(input_mtok=Decimal('0.15'), output_mtok=Decimal('0.45'))),
        ({'service_tier': 'priority'}, ModelPrice(input_mtok=Decimal('0.8'), cache_read_mtok=Decimal('0.06'))),
    ]
    assert flat.price_variants[0].constraint == StartDateConstraint(start_date=today)
    assert len(flat.price_variants) == 7
    tiered = provider.find_model('tiered')
    assert tiered is not None and tiered.price_variants is not None
    assert tiered.price_variants[0].prices == ModelPrice(
        input_mtok=TieredPrices(base=Decimal('1.5'), tiers=[Tier(start=200_000, price=Decimal('3'))])
    )
    uneven = provider.find_model('uneven')
    assert uneven is not None and uneven.price_variants is not None
    assert uneven.price_variants[0].prices == ModelPrice(input_mtok=Decimal('0.5'), output_mtok=Decimal('3'))
    assert uneven.price_variants[1].prices == ModelPrice(input_mtok=Decimal('0.25'), cache_read_mtok=Decimal('0.1'))
    assert capsys.readouterr().out == (
        "Mistral: tiered {'service_tier': 'flex'} rates are not one share of the standard rates; update them by hand\n"
        "Mistral: uneven {'processing': 'batch'} rates are not one share of the standard rates; update them by hand\n"
        "Mistral: uneven {'service_tier': 'flex'} rates are not one share of the standard rates; update them by hand\n"
        "Mistral: tiered-again {'processing': 'batch'} rates are not one share of the standard rates; update them by hand\n"
    )

    models[0] = model('flat', input_mtok='0.5', cache_read_mtok='0.03', output_mtok='1.2')
    ProviderYaml(provider_path).upsert_models(models[:1], source='Mistral', min_count=1)
    flat = ProviderYaml(provider_path).provider.find_model('flat')
    assert flat is not None and flat.price_variants is not None
    assert len(flat.price_variants) == 7
    assert flat.price_variants[0].prices == ModelPrice(input_mtok=Decimal('0.25'), output_mtok=Decimal('0.6'))
    assert '{ processing: batch }' in provider_path.read_text()
