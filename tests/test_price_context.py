from __future__ import annotations

import json
import warnings
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest

from genai_prices import UpdatePrices, Usage, calc_price, extract_usage
from genai_prices.data_snapshot import set_custom_snapshot
from genai_prices.types import AbstractUsage, CalcPrice, ModelPrice, PriceVariant
from prices import prices_types
from prices.build import load_units
from prices.export_validation import validate_export_payload

FIXTURE: dict[str, Any] = json.loads((Path(__file__).parent / 'fixtures/price_context.json').read_text())


@pytest.fixture
def context_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    def get(url: str, timeout: httpx2.Timeout) -> httpx2.Response:
        assert timeout is not None
        return httpx2.Response(200, json=FIXTURE['providers'], request=httpx2.Request('GET', url))

    monkeypatch.setattr(httpx2, 'get', get)
    set_custom_snapshot(UpdatePrices().fetch())


@pytest.mark.usefixtures('context_prices')
@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda case: case['name'])
def test_price_context_contract(case: dict[str, Any]) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        result = calc_price(
            Usage(**FIXTURE['usage']),
            'context-model',
            provider_id='testing',
            genai_request_timestamp=datetime.fromisoformat(case['timestamp']),
            price_context=case.get('context'),
        )
    assert result.input_price == Decimal(str(case['input']))
    assert result.output_price == Decimal(str(case['output']))
    assert result.total_price == Decimal(str(case['total']))
    assert [str(w.message) for w in caught] == (
        ["No price variant matched for model 'context-model'; using standard prices"] if case.get('warn') else []
    )


@pytest.mark.parametrize(
    'model,tier,total',
    [
        ('o3', 'flex', '4.8125'),
        ('o3', 'priority', '16.84375'),
        ('o4-mini', 'flex', '2.646875'),
        ('o4-mini', 'priority', '9.625'),
        ('gpt-5-mini', 'flex', '1.096875'),
        ('gpt-6.1-sol', 'fast', '36.1'),
        ('gpt-6.1-sol', 'priority', '36.1'),
    ],
)
def test_openai_service_tiers(model: str, tier: str, total: str) -> None:
    result = calc_price(
        Usage(input_tokens=1_000_000, cache_read_tokens=250_000, output_tokens=1_000_000),
        model,
        provider_id='openai',
        genai_request_timestamp=datetime(2026, 10, 12),
        price_context={'service_tier': tier},
    )
    assert result.total_price == Decimal(total)


def test_extracted_context_and_no_mutation() -> None:
    response = {
        'model': 'o3',
        'service_tier': 'flex',
        'usage': {'prompt_tokens': 1_000_000, 'completion_tokens': 1_000_000},
    }
    extracted = extract_usage(response, provider_id='openai', api_flavor='chat')
    for tier, total in [('flex', '5'), ('default', '10'), ('priority', '17.5'), ('flex', '5')]:
        assert extracted.calc_price(
            price_context={'service_tier': tier}, genai_request_timestamp=datetime(2026, 10, 12)
        ).total_price == Decimal(total)


def test_unresearched_tier_history_and_unsupported_model() -> None:
    for model, timestamp in [('o3', datetime(2026, 10, 11)), ('text-embedding-3-small', datetime(2026, 10, 12))]:
        standard = calc_price(
            Usage(input_tokens=1_000_000), model, provider_id='openai', genai_request_timestamp=timestamp
        )
        with pytest.warns(UserWarning, match='No price variant matched'):
            result = calc_price(
                Usage(input_tokens=1_000_000),
                model,
                provider_id='openai',
                genai_request_timestamp=timestamp,
                price_context={'service_tier': 'flex'},
            )
        assert result.total_price == standard.total_price


def test_fallback_provider_does_not_inherit_tier_rates() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    timestamp = datetime(2026, 10, 12)
    standard = calc_price(usage, 'gpt-5', provider_id='azure', genai_request_timestamp=timestamp)
    assert standard.total_price == Decimal('11.25')
    for context in [None, {}, {'service_tier': 'priority'}]:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            result = calc_price(
                usage, 'gpt-5', provider_id='azure', genai_request_timestamp=timestamp, price_context=context
            )
        assert result.provider.id == 'azure'
        assert result.total_price == standard.total_price
        assert [str(w.message) for w in caught] == (
            ["No price variant matched for provider 'azure' model 'gpt-5'; using standard prices"] if context else []
        )


@pytest.mark.parametrize('when', [{}, {'service_tier': None}, {'service_tier': True}])
def test_invalid_variant_condition(when: Any) -> None:
    with pytest.raises(ValueError, match='Price variant when'):
        PriceVariant(when=when, prices=ModelPrice(input_mtok=Decimal('1')))


def test_variant_export_validation() -> None:
    provider = prices_types.Provider.model_validate(FIXTURE['providers'][0])
    validate_export_payload([provider], load_units())
    assert provider.models[0].price_variants is not None
    provider.models[0].price_variants[0].prices = prices_types.ModelPrice.model_validate({'cache_image_read_mtok': 1})
    with pytest.raises(ValueError, match='Invalid price variant'):
        validate_export_payload([provider], load_units())


def test_variant_export_validation_covers_combined_overrides() -> None:
    provider = prices_types.Provider.model_validate(
        {
            'id': 'example',
            'name': 'Example',
            'api_pattern': 'example',
            'models': [
                {
                    'id': 'm',
                    'match': {'equals': 'm'},
                    'prices': {'input_mtok': 1},
                    'price_variants': [
                        {'when': {'service_tier': 'flex'}, 'prices': {'cache_read_mtok': 1}},
                        {'when': {'inference_geo': 'us'}, 'prices': {'input_image_mtok': 1}},
                    ],
                }
            ],
        }
    )
    with pytest.raises(ValueError, match='Missing join price'):
        validate_export_payload([provider], load_units())


def test_variant_export_validation_covers_later_variant_alone() -> None:
    provider = prices_types.Provider.model_validate(
        {
            'id': 'example',
            'name': 'Example',
            'api_pattern': 'example',
            'models': [
                {
                    'id': 'm',
                    'match': {'equals': 'm'},
                    'prices': {'input_mtok': 1},
                    'price_variants': [
                        {'when': {'service_tier': 'flex'}, 'prices': {'input_audio_mtok': 1}},
                        {'when': {'inference_geo': 'us'}, 'prices': {'cache_read_mtok': 1, 'cache_audio_read_mtok': 1}},
                    ],
                }
            ],
        }
    )
    with pytest.raises(ValueError, match='Invalid price variant.*Missing ancestor price'):
        validate_export_payload([provider], load_units())


def test_variant_preserves_model_price_subclass() -> None:
    from genai_prices.types import ClauseEquals, ModelInfo, Provider

    class CustomPrice(ModelPrice):
        def calc_price(self, usage: AbstractUsage) -> CalcPrice:
            result = super().calc_price(usage)
            result['total_price'] += Decimal('1')
            return result

    model = ModelInfo(
        id='custom',
        match=ClauseEquals('custom'),
        prices=CustomPrice(input_mtok=Decimal('4')),
        price_variants=[PriceVariant({'service_tier': 'flex'}, ModelPrice(input_mtok=Decimal('2')))],
    )
    provider = Provider(id='custom', name='Custom', api_pattern='custom', models=[model])
    assert (
        model.calc_price(Usage(input_tokens=1_000_000), provider, price_context={'service_tier': 'flex'}).total_price
        == 3
    )
    assert model.calc_price(Usage(input_tokens=1_000_000), provider).total_price == 5
