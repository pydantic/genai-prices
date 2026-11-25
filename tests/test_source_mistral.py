from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from prices import source_mistral
from prices.prices_types import (
    ClauseEquals,
    ConditionalPrice,
    ModelInfo,
    ModelPrice,
    StartDateConstraint,
    Tier,
    TieredPrices,
)
from prices.update import ProviderYaml


def catalog_model(name: str, api_ids: list[str], *rates: tuple[str, float, str | None], **extra: object) -> object:
    pricing = [{'label': label, 'priceUsd': price, 'unit': unit} for label, price, unit in rates]
    return {'name': name, 'modelIds': api_ids, 'isFree': False, 'pricing': pricing} | extra


def pricing_page(*models: object) -> str:
    """The docs page as Next.js serves it: a flight row of catalog JSON inside a `self.__next_f` script."""
    row = f'1:["$","div",null,{json.dumps({"models": list(models)})}]\n2:I["chunk"]\n'
    return f'<html><script>self.__next_f.push([1,{json.dumps(row)}])</script></html>'


def test_mistral_parses_token_page_and_audio_rates_and_skips_unsupported_units() -> None:
    large = catalog_model(
        'Mistral Large 4',
        ['mistral-large-4', 'mistral-large-latest'],
        ('Input', 0.7, '/M Tokens'),
        ('Cached input', 0.07, '/M Tokens'),
        ('Output', 2.1, '/M Tokens'),
    )
    page = pricing_page(
        large,
        catalog_model(
            'OCR 4.1', ['mistral-ocr-4-1'], ('Input', 4, '/1000 Pages'), ('Input', 5, '/1000 Annotated Pages')
        ),
        catalog_model('Voxtral Mini Transcribe 3', ['voxtral-mini-transcribe-3-0'], ('Input', 0.0035, '/Min')),
        catalog_model('Voxtral TTS', ['voxtral-mini-tts-2603'], ('Input', 0, '/M Chars'), ('Output', 16, '/M Chars')),
        catalog_model('Mistral Moderation 2', ['mistral-moderation-2603'], ('Input', 0, '/M Tokens'), isFree=True),
        catalog_model('Mistral 7B', [], ('Input (/M tokens)', 0.25, None)),
        catalog_model(
            'Embed',
            ['mistral-embed'],
            ('Input', 0.1, '/M Tokens'),
            ('Output', 0, '/M Chars'),
            # Listed only among another model's related models, like a deprecated model on the live page.
            relatedModels=[
                catalog_model('Mistral Medium 3.5', ['mistral-medium-3-5'], ('Input', 1.5, '/M Tokens')),
                large,
            ],
        ),
    )

    models = source_mistral.parse_pricing_page(page)

    assert [(model.id, model.name, model.prices_checked) for model in models] == [
        ('mistral-large-4', 'Mistral Large 4', date.today()),
        ('mistral-ocr-4-1', 'OCR 4.1', date.today()),
        ('voxtral-mini-transcribe-3-0', 'Voxtral Mini Transcribe 3', date.today()),
        ('mistral-medium-3-5', 'Mistral Medium 3.5', date.today()),
        ('mistral-embed', 'Embed', date.today()),
    ]
    assert [model.prices for model in models] == [
        ModelPrice(input_mtok=Decimal('0.7'), cache_read_mtok=Decimal('0.07'), output_mtok=Decimal('2.1')),
        ModelPrice.model_validate({'input_document_kpages': 4, 'input_annotated_document_kpages': 5}),
        ModelPrice.model_validate({'audio_hours': '0.21', 'input_audio_hours': '0.21'}),
        ModelPrice(input_mtok=Decimal('1.5')),
        ModelPrice(input_mtok=Decimal('0.1')),
    ]


def test_mistral_reports_a_model_listed_at_conflicting_rates(capsys: pytest.CaptureFixture[str]) -> None:
    page = pricing_page(
        catalog_model('Codestral', ['codestral-2508'], ('Input', 0.3, '/M Tokens')),
        catalog_model('Codestral', ['codestral-2508'], ('Input', 0.4, '/M Tokens')),
        catalog_model('Mistral Embed', ['mistral-embed'], ('Input', 0.1, '/M Tokens')),
    )

    assert [model.id for model in source_mistral.parse_pricing_page(page)] == ['mistral-embed']
    assert capsys.readouterr().out == (
        'Mistral: kept codestral-2508 unchanged, the pricing page lists it at conflicting rates; update it by hand\n'
    )


@pytest.mark.parametrize(
    ('model', 'missing'),
    [
        ({'name': 'Codestral', 'modelIds': ['codestral'], 'isFree': False}, 'pricing'),
        (
            {'name': 'Codestral', 'modelIds': ['codestral'], 'isFree': False, 'pricing': [{'label': 'Input'}]},
            'priceUsd',
        ),
    ],
)
def test_mistral_rejects_a_catalog_model_in_an_unexpected_shape(model: dict[str, object], missing: str) -> None:
    with pytest.raises(ValidationError, match=missing):
        source_mistral.parse_pricing_page(pricing_page(model))


@pytest.mark.vcr()
def test_mistral_main_fetches_recorded_pricing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'mistral.yml'
    provider_path.write_text(
        """\
id: mistral
name: Mistral
api_pattern: mistral
models:
  - id: mistral-large-4
    match: { equals: mistral-large-4 }
    prices: { input_mtok: 1, cache_read_mtok: 0.1, output_mtok: 3 }
"""
    )

    source_mistral.main(provider_path)

    assert capsys.readouterr().out == 'Mistral prices updated: 17 added, 1 updated\n'
    provider = ProviderYaml(provider_path).provider
    assert len(provider.models) == 18
    large = provider.find_model('mistral-large-4')
    assert large is not None
    assert large.prices == [
        ConditionalPrice(
            prices=ModelPrice(input_mtok=Decimal('1'), cache_read_mtok=Decimal('0.1'), output_mtok=Decimal('3'))
        ),
        ConditionalPrice(
            constraint=StartDateConstraint(start_date=date.today()),
            prices=ModelPrice(input_mtok=Decimal('0.7'), cache_read_mtok=Decimal('0.07'), output_mtok=Decimal('2.1')),
        ),
    ]

    source_mistral.main(provider_path)
    assert capsys.readouterr().out == 'Mistral prices updated: 0 added, 18 updated\n'
    assert ProviderYaml(provider_path).provider == provider


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
    assert flat.price_variants[0].prices == ModelPrice(input_mtok=Decimal('0.2'), output_mtok=Decimal('0.6'))
    assert 'cannot be represented by date-only constraints' in capsys.readouterr().out
    assert '{ processing: batch }' in provider_path.read_text()
